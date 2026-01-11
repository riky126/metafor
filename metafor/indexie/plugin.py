
import asyncio
import inspect
import contextlib
from typing import Any, Dict, Optional, Callable, List, TypeVar, Generic, Union
from enum import Enum
from js import console, navigator
from metafor.form.schema import Schema
from metafor.core import create_signal

from .support import Support, IndexedDBError, StorageError, _to_js_obj

class Strategy(Enum):
    LOCAL_FIRST = "local_first"
    NETWORK_FIRST = "network_first"

class HookRegistrar:
    def __init__(self):
        self._hooks = {}

    def on_add(self, callback: Callable, priority_invoke: bool = False):
        self._register("on_add", callback, priority_invoke=priority_invoke)

    def on_update(self, callback: Callable, priority_invoke: bool = False):
        self._register("on_update", callback, priority_invoke=priority_invoke)

    def on_delete(self, callback: Callable, priority_invoke: bool = False):
        self._register("on_delete", callback, priority_invoke=priority_invoke)

    def _register(self, event: str, callback: Callable, priority_invoke: bool = False):
        if event not in self._hooks:
            self._hooks[event] = []
        
        if priority_invoke:
            self._hooks[event].insert(0, callback)
        else:
            self._hooks[event].append(callback)

    async def _trigger(self, event: str, payload: Any):
        if event in self._hooks:
            for cb in self._hooks[event]:
                res = cb(payload)
                if inspect.iscoroutine(res):
                    await res


class DirectTransaction:
    """
    Transaction handler for offline direct-write mode.
    
    In this mode, there is no in-memory buffer. Operations (add/put/delete) are
    executed immediately against the underlying database to ensure they are
    captured by the Sync Queue hooks as soon as possible.
    
    Therefore, 'commit' is a no-op because the data is already persisted.
    """
    def __init__(self, table):
        self.table = table

    async def add(self, item: Dict[str, Any], key: Any = None):
        return await self.table.add(item, key)

    async def put(self, item: Dict[str, Any], key: Any = None):
        return await self.table.put(item, key)

    async def delete(self, key: Any):
        return await self.table.delete(key)

    async def commit(self):
        # Auto-commit: Operations were already executed directly on the DB.
        pass

    async def rollback(self):
        console.warn("Rollback is not supported in offline direct-write mode (operations are auto-committed).")

class OverlayLayer:
    """In-memory layer for optimistic transactions."""
    def __init__(self, table: 'Table'):
        self.table = table
        self.mutations: Dict[Any, Dict[str, Any]] = {} # key -> {type: "put"|"delete", value: ...}
        self.active = False
        self.visible = True 
        
    def add(self, item: Dict[str, Any], key: Any = None):
        if not key:
            if self.table.primary_key in item:
                key = item[self.table.primary_key]
            else:
                import random
                key = -random.randint(1, 1000000)
                item[self.table.primary_key] = key
        
        self.mutations[key] = {"type": "add", "value": item}
        # Only trigger reactivity version update, NOT hooks (to avoid Sync Queue)
        if self.visible:
             self.table._set_version(self.table._version.peek() + 1)
        return key
        
    def put(self, item: Dict[str, Any], key: Any = None):
        pk = key or item.get(self.table.primary_key)
        if not pk:
             import random
             pk = -random.randint(1, 1000000)
             item[self.table.primary_key] = pk
             
        self.mutations[pk] = {"type": "put", "value": item}
        if self.visible:
             self.table._set_version(self.table._version.peek() + 1)
        return pk
        
    def delete(self, key: Any):
        self.mutations[key] = {"type": "delete"}
        if self.visible:
             self.table._set_version(self.table._version.peek() + 1)
        
    def clear(self):
        self.mutations.clear()
        
    async def commit(self):
        """Persist changes to IDB."""
        self.active = False
        try:
             keys = list(self.mutations.keys())
             for key in keys:
                 op = self.mutations[key]
                 if op["type"] == "add":
                     is_temp_key = isinstance(key, int) and key < 0
                     val = op["value"].copy()
                     if is_temp_key and self.table.primary_key in val:
                         del val[self.table.primary_key]
                     await self.table.add(val, silent=False, optimistic=self.visible)

                 elif op["type"] == "put":
                     is_temp_key = isinstance(key, int) and key < 0
                     
                     if is_temp_key and self.table.primary_key:
                         val = op["value"].copy()
                         if self.table.primary_key in val:
                             del val[self.table.primary_key]
                         await self.table.put(val, silent=False, optimistic=self.visible)
                     else:
                         await self.table.put(op["value"], key=key, silent=False, optimistic=self.visible)
                         
                 elif op["type"] == "delete":
                     await self.table.delete(key, silent=False, optimistic=self.visible)
             
             self.mutations.clear()
        except Exception as e:
             self.active = True
             raise e

    async def rollback(self):
        self.mutations.clear()
        self.active = False
        if self.visible:
             self.table._set_version(self.table._version.peek() + 1)
        self.visible = True


class Table:
    def __init__(self, name: str, db: 'Indexie', primary_key: str = None, strategy: Strategy = Strategy.LOCAL_FIRST, schema: Schema = None):
        self.name = name
        self.db = db
        self.primary_key = primary_key
        self.strategy = strategy
        self.schema = schema
        self._version, self._set_version = create_signal(0)
        self._hook_registrar = HookRegistrar()
        self._overlay = OverlayLayer(self)
        self._server_push = None
        
    @contextlib.asynccontextmanager
    async def start_transaction(self, optimistic: bool = False):
        # Check Network Status
        if self.db.sync_manager:
            is_online = self.db.sync_manager.is_online
        else:
            is_online = navigator.onLine
        
        if not is_online:
            # Offline: Write directly to DB (triggering hooks for Sync Queue)
            yield DirectTransaction(self)
        else:
            # Online: Use Optimistic Overlay (suppressing hooks to avoid Sync Queue)
            self._overlay.active = True
            self._overlay.visible = optimistic
            try:
                yield self._overlay
            except Exception:
                 await self._overlay.rollback()
                 raise
            finally:
                 if self._overlay.active:
                      await self._overlay.rollback()
        
    def attach_schema(self, schema: Schema):
        """Attaches a validation schema to the table."""
        self.schema = schema
        return self

    def _validate_item(self, item: Dict[str, Any]):
        if self.schema:
            errors = self.schema.validate(item)
            if errors:
                raise StorageError(f"Validation failed for table '{self.name}': {errors}")

    @property
    def hook(self):
        return self._hook_registrar
        
    async def _trigger_hook(self, event: str, payload: Any):
        await self._hook_registrar._trigger(event, payload)
        
    async def add(self, item: Dict[str, Any], key: Any = None, silent: bool = False, optimistic: bool = False):
        # Validate before any operation
        self._validate_item(item)
        
        # Overlay
        if self._overlay.active:
             res = self._overlay.add(item, key)
             return res

        res = await self.db.query_engine.add(self.name, item, key)
        self._set_version(self._version.peek() + 1)
        if not silent:
             await self._trigger_hook("on_add", {"item": item, "key": res, "optimistic": optimistic})
        return res
        
    async def put(self, item: Dict[str, Any], key: Any = None, silent: bool = False, optimistic: bool = False):
        # Validate before any operation
        self._validate_item(item)

        pk_val = key or item.get(self.primary_key)
        
        # 1. Overlay
        if self._overlay.active:
             res = self._overlay.put(item, key)
             return res
        
        # Capture base_rev for Revision Tree
        old_item = await self.get(pk_val) if pk_val is not None else None
        
        base_rev = old_item.get("_rev") if old_item else None
        
        # --- Revision Rotation (Only for local writes) ---
        if not silent:
            from .support import _set_revision
            _set_revision(item, parent_rev=base_rev)

        if self.strategy == Strategy.NETWORK_FIRST and not silent:
            # For Network First, we trigger before IDB call
            await self._trigger_hook("on_update", {"item": item, "key": pk_val, "base_rev": base_rev, "base_doc": old_item, "optimistic": optimistic})
            
            res = await self.db.query_engine.put(self.name, item, key)
            self._set_version(self._version.peek() + 1)
            return res
        else:
            res = await self.db.query_engine.put(self.name, item, key)
            self._set_version(self._version.peek() + 1)
            if not silent:
                # IMPORTANT: Use 'res' here because pk_val might be None for new records (auto-increment)
                await self._trigger_hook("on_update", {"item": item, "key": res, "base_rev": base_rev, "base_doc": old_item, "optimistic": optimistic})
            return res
        
    def get(self, key: Any):
        self._version() 
        
        async def _run():
            if self._overlay.active and self._overlay.visible:
                 if key in self._overlay.mutations:
                     op = self._overlay.mutations[key]
                     if op['type'] == 'delete':
                         return None
                     return op['value']
            
            return await self.db.query_engine.get(self.name, key)
        return _run()
        
    async def delete(self, key: Any, silent: bool = False, optimistic: bool = False):
        if self._overlay.active:
             self._overlay.delete(key)
             return
             
        # Capture base_rev for Tombstone
        old_item = await self.get(key) if key is not None else None
        base_rev = old_item.get("_rev") if old_item else None

        if self.strategy == Strategy.NETWORK_FIRST and not silent:
             await self._trigger_hook("on_delete", {"key": key, "all": False, "base_rev": base_rev, "base_doc": old_item, "optimistic": optimistic})
             
             res = await self.db.query_engine.delete(self.name, key)
             self._set_version(self._version.peek() + 1)
             return res
        else:
            res = await self.db.query_engine.delete(self.name, key)
            self._set_version(self._version.peek() + 1)
            if not silent:
                await self._trigger_hook("on_delete", {"key": key, "all": False, "base_rev": base_rev, "base_doc": old_item, "optimistic": optimistic})
            return res
        
    async def clear(self, silent: bool = False, optimistic: bool = False):
         res = await self.db.query_engine.clear(self.name)
         self._set_version(self._version.peek() + 1)
         if not silent:
             await self._trigger_hook("on_delete", {"key": None, "all": True, "optimistic": optimistic})
         return res

    def drop(self):
        if not self.db._db_instance:
             raise IndexedDBError("Database instance not available for drop()")
        self.db._db_instance.deleteObjectStore(self.name)

    async def update(self, key: Any, changes: Union[Dict[str, Any], Callable[[Dict[str, Any]], None]], silent: bool = False, optimistic: bool = False):
        obj = await self.get(key)
        
        if obj is None:
             console.log(f"Table.update: Key {key} not found. Changes type: {type(changes)}")
             if isinstance(changes, dict):
                 obj = changes
             else:
                 raise IndexedDBError(f"Key {key} not found in {self.name} and cannot upsert with callable")
        else:
            if callable(changes):
                changes(obj) 
            else:
                obj.update(changes)
        
        await self.put(obj, silent=silent, optimistic=optimistic) 
        return True

    async def sync_electric(self, url: str, params: Dict[str, Any] = None, headers: Dict[str, str] = None, http_client = None):
        return await Support.sync_electric(self, url, params, headers, http_client)
 
    def to_array(self):
        return Collection(self, None).to_array()
        
    def count(self):
        return Collection(self, None).count()
        
    def where(self, index: str):
        return WhereClause(self, index)

    def order_by(self, key: str):
        c = Collection(self, None) 
        c.index = key 
        c._order_by = key
        return c
        
    def limit(self, n: int):
        c = Collection(self, None)
        c.limit(n)
        return c
        
    def filter(self, fn):
        c = Collection(self, None)
        c.filter(fn)
        return c

    def offset(self, n: int):
        c = Collection(self, None)
        c.offset(n)
        return c
        
    def reverse(self):
        c = Collection(self, None)
        c.reverse()
        return c

    async def _execute_query(self, collection: 'Collection'):
        return await self.db.query_engine.execute_query(collection)
        
    async def _execute_count(self, collection: 'Collection'):
        return await self.db.query_engine.count(collection)

    async def _execute_delete(self, collection: 'Collection'):
        count = await self.db.query_engine.delete_many(collection)
        if count > 0:
            self._set_version(self._version.peek() + 1)
        return count

class WhereClause:
    def __init__(self, table, index: str, collection: 'Collection' = None):
        self.table = table
        self.index = index
        self.collection = collection
        
    def _attach(self, op, value):
        if self.collection:
            self.collection._add_condition(self.index, op, value)
            return self.collection
        return Collection(self.table, self.index, op, value)

    def equals(self, value):
        return self._attach("equals", value)
        
    def above(self, value):
        return self._attach("above", value)
    
    def below(self, value):
        return self._attach("below", value)
        
    def starts_with(self, value):
        return self._attach("starts_with", value)


class Collection:
    def __init__(self, table, index=None, op=None, value=None):
        self.table = table
        self._conditions = []
        if index:
            self._conditions.append({"index": index, "op": op, "value": value})
            
        self._limit = None
        self._offset = 0
        self._order_by = None
        self._reverse = False
        self._filter_fn = None
    
    def _add_condition(self, index, op, value):
        self._conditions.append({"index": index, "op": op, "value": value})

    def or_(self, index: str):
        return WhereClause(self.table, index, collection=self)
    
    def limit(self, n: int):
        self._limit = n
        return self
        
    def offset(self, n: int):
        self._offset = n
        return self
        
    def reverse(self):
        self._reverse = True
        return self
        
    def order_by(self, key: str):
        self._order_by = key
        return self
        
    def filter(self, fn: Callable[[Any], bool]):
        self._filter_fn = fn
        return self

    async def each(self, fn: Callable[[Any], None]):
        items = await self.to_array()
        for item in items:
            res = fn(item)
            if inspect.iscoroutine(res):
                await res
    
    def to_array(self) -> List[Dict[str, Any]]:
        self.table._version() # Track dependency
        async def _call_execute_query():
             return await self.table._execute_query(self)
        return _call_execute_query()

    def first(self) -> Optional[Dict[str, Any]]:
        self.table._version() 
        async def _run():
            original_limit = self._limit
            self._limit = 1
            results = await self.to_array()
            self._limit = original_limit 
            return results[0] if results else None
        return _run()
        
    def count(self) -> int:
         self.table._version()
         async def _run():
             return await self.table._execute_count(self)
         return _run()
         
    async def delete(self) -> int:
        return await self.table._execute_delete(self)

class Version:
    def __init__(self, db, version_number):
        self.db = db
        self.version_number = version_number
        self.schema_definitions = {}
        self.upgrade_callback = None

    def stores(self, schema: Dict[str, str]):
        self.schema_definitions = schema
        self.db._register_version(self)
        return self

    def upgrade(self, fn: Callable):
        self.upgrade_callback = fn
        return self
