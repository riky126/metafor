
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
        
        # Prevent duplicate registration of functionally identical callbacks.
        # Identity check handles same object.
        # Name + Bytecode check handles re-definitions during component re-renders.
        if callback in self._hooks[event]:
            return
        
        # Structural check for reactive environments
        if any(cb.__name__ == callback.__name__ and cb.__code__ == callback.__code__ 
               for cb in self._hooks[event]):
            return

        if priority_invoke:
            self._hooks[event].insert(0, callback)
        else:
            self._hooks[event].append(callback)

    async def _trigger(self, event: str, payload: Any):
        if event in self._hooks:
            # Taking a snapshot of the hooks list prevents newly registered hooks 
            # (from re-renders mid-await) from being triggered in the current loop.
            for cb in list(self._hooks[event]):
                res = cb(payload)
                if inspect.iscoroutine(res):
                    await res




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
                import uuid
                key = str(uuid.uuid4())
                item[self.table.primary_key] = key
        
        self.mutations[key] = {"type": "add", "value": item}
        # Only trigger reactivity version update, NOT hooks (to avoid Sync Queue)
        if self.visible:
             self.table._set_version(self.table._version.peek() + 1)
        return key
        
    def put(self, item: Dict[str, Any], key: Any = None):
        pk = key or item.get(self.table.primary_key)
        if not pk:
             import uuid
             pk = str(uuid.uuid4())
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
                     # No longer stripping temp keys; UUIDs are permanent
                     val = op["value"]
                     # Use silent=self.visible because if visible=True (optimistic), hooks triggered in overlay.
                     # If visible=False, hooks were NOT triggered, so we must trigger them now (silent=False).
                     # We force optimistic=True so that SyncManager treats this as an optimistic sync (skips queue, enriches payload)
                     await self.table.add(val, silent=self.visible, optimistic=True)

                 elif op["type"] == "put":
                     # No longer stripping temp keys
                     await self.table.put(op["value"], key=key, silent=self.visible, optimistic=True)
                         
                 elif op["type"] == "delete":
                     # To match optimistic behavior (which triggers "on_delete"), we must manually trigger it
                     # and suppress the default "on_update" (soft delete) from Table.delete.
                     # We force optimistic=True here as well for consistency.
                     await self.table.delete(key, silent=True, optimistic=True)
                     
                     if not self.visible:
                          await self.table._trigger_hook("on_delete", {
                              "key": key,
                              "all": False,
                              "base_rev": None,
                              "base_doc": None,
                              "optimistic": True
                          })
             
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
        """
        Starts a managed transaction. 
        Highly Recommended for Optimistic UI and guaranteed Atomic Commits.
        """
        self._overlay.active = True
        self._overlay.visible = optimistic
        try:
            yield self._overlay
        except Exception:
             await self._overlay.rollback()
             raise
        finally:
             # If the transaction block finishes without an explicit commit(),
             # it will be automatically rolled back to prevent stale memory state.
             if self._overlay.active:
                  await self._overlay.rollback()
        
    def attach_schema(self, schema: Schema):
        """Attaches a validation schema to the table."""
        self.schema = schema
        return self

    def sync_enroll(self):
        """Enroll this table in the sync process."""
        if hasattr(self.db, "sync_manager") and self.db.sync_manager:
            self.db.sync_manager.enroll_table(self.name)
        else:
             # Buffer enrollment if SyncManager not yet created
             if hasattr(self.db, "_sync_enrollments"):
                 self.db._sync_enrollments.add(self.name)
             else:
                 from js import console
                 console.warn(f"Cannot enroll {self.name}: SyncManager not enabled on DB.")


    def _validate_item(self, item: Dict[str, Any]):
        # Skip validation for tombstones (deleted records)
        if item.get("_deleted") or item.get("deleted"):
            return

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
        if not self.db._db_instance: 
            await self.db._ensure_open()

        # Sanitize: Ensure new records are NOT marked as deleted
        if isinstance(item, dict):
            item.pop("_deleted", None)
            item.pop("deleted", None)
            
        # Validate before any operation
        self._validate_item(item)
        
        # Overlay
        if self._overlay.active:
            optimistic = True # Default to optimistic if overlay is active
            res = self._overlay.add(item, key)
            if not silent and self._overlay.visible:
                 # Trigger hook immediately for Optimistic Sync/Manual Control
                 await self._trigger_hook("on_add", {"value": item, "key": res, "optimistic": True})
            return res

        res = await self.db.query_engine.add(self.name, item, key)
        self._set_version(self._version.peek() + 1)
        if not silent:
             await self._trigger_hook("on_add", {"value": item, "key": res, "optimistic": optimistic})
        return res
        
    async def put(self, item: Dict[str, Any], key: Any = None, silent: bool = False, optimistic: bool = False):
        if not self.db._db_instance: 
            await self.db._ensure_open()



        # Validate before any operation
        self._validate_item(item)

        pk_val = key or item.get(self.primary_key)
        
        # 1. Overlay
        # 1. Overlay
        if self._overlay.active:
            optimistic = True # Default to optimistic if overlay is active
            
            # Capture base_rev/base_doc BEFORE updating the overlay
            old_item = None
            if not silent and self._overlay.visible:
                 old_item = await self.get(pk_val) if pk_val is not None else None
            
            base_rev = old_item.get("_rev") if old_item else None
            
            res = self._overlay.put(item, key)
            
            if not silent and self._overlay.visible:
                 # For optimistic manual sync, we need to provide base_rev to SyncManager refinement
                 await self._trigger_hook("on_update", {
                     "value": item, 
                     "key": res, 
                     "base_rev": base_rev, 
                     "base_doc": old_item,
                     "optimistic": True
                 })
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
            await self._trigger_hook("on_update", {"value": item, "key": pk_val, "base_rev": base_rev, "base_doc": old_item, "optimistic": optimistic})
            
            res = await self.db.query_engine.put(self.name, item, key)
            self._set_version(self._version.peek() + 1)
            return res
        else:
            res = await self.db.query_engine.put(self.name, item, key)
            self._set_version(self._version.peek() + 1)
            if not silent:
                # IMPORTANT: Use 'res' here because pk_val might be None for new records (auto-increment)
                await self._trigger_hook("on_update", {"value": item, "key": res, "base_rev": base_rev, "base_doc": old_item, "optimistic": optimistic})
            return res
        
    def get(self, key: Any, include_deleted: bool = False):
        self._version() 
        
        async def _run():
            if self._overlay.active and self._overlay.visible:
                 if key in self._overlay.mutations:
                     op = self._overlay.mutations[key]
                     if op['type'] == 'delete':
                         return None if not include_deleted else op['value']
                     
                     val = op['value']
                     # Soft Delete in Overlay
                     if not include_deleted and val and (val.get("_deleted") or val.get("deleted")):
                         return None
                     return val
            
            return await self.db.query_engine.get(self.name, key, include_deleted=include_deleted)
        return _run()
        
    async def delete(self, key: Any, silent: bool = False, optimistic: bool = False, hard: bool = False):
        if not self.db._db_instance: 
            await self.db._ensure_open()
            
        # Default to optimistic if overlay is active
        if self._overlay.active:
            optimistic = True
            
        # Optimization: Don't pre-fetch base_doc/base_rev for deletes unless absolutely necessary.
        # User confirmed base_doc can be None for delete flow.
        old_item = None
        base_rev = None
             
        if self._overlay.active:
             # Overlay deletions are effectively "hard" semantic in that the item serves as a deletion
             # The underlying commit will call table.delete which will handle soft/hard based on default or context.
             # Actually overlay just records "delete".
             self._overlay.delete(key)
             if not silent and self._overlay.visible:
                  # Trigger hook
                  await self._trigger_hook("on_delete", {
                      "key": key, 
                      "all": False, 
                      "base_rev": base_rev, 
                      "base_doc": old_item,
                      "optimistic": True
                  })
             return
        
        # Capture base_rev for Sync/Tombstone
        if not silent or not hard:
             item = await self.get(key, include_deleted=True)
             if item:
                 base_rev = item.get("_rev")
                 old_item = item

        if hard:
            # Perform Hard Delete in DB (e.g. for _sys_ tables)
            await self.db.query_engine.delete(self.name, key)
            self._set_version(self._version.peek() + 1)
            
            if not silent:
                 await self._trigger_hook("on_delete", {
                      "key": key, 
                      "all": False, 
                      "base_rev": base_rev, 
                      "base_doc": old_item,
                      "optimistic": optimistic
                 })
            return

        # --- Soft Delete Mode (Default) ---
        
        if old_item is None:
             # Non-existent item: Check if we need to support "Delete by ID" (Blind Delete)
             # To support syncing deletions of items we don't have locally (e.g. lost state), 
             # we create a minimal tombstone.
             tombstone = {"_deleted": True}
             if self.primary_key:
                 tombstone[self.primary_key] = key
        else:
             # Idempotency Check
             if old_item.get("_deleted") or old_item.get("deleted"):
                 return

            # Strip fields to release constraints (RxDB Style)
             keys_to_keep = {"_rev", "_id", "uuid", "id", "_lastModified"}
             if self.primary_key:
                 keys_to_keep.add(self.primary_key)
                
             tombstone = {k: v for k, v in old_item.items() if k in keys_to_keep}
             tombstone["_deleted"] = True

        # Optimized Write: Bypass self.put() to avoid double-read of old_item
        # We manually handle revisioning and hooks here.
        
        if not silent:
            from .support import _set_revision
            _set_revision(tombstone, parent_rev=base_rev)

        # Write directly to QueryEngine
        res = await self.db.query_engine.put(self.name, tombstone, key)
        self._set_version(self._version.peek() + 1)

        if not silent:
            # Trigger 'on_update' because soft-delete is technically an update.
            # SyncManager listens to this and queues it as "delete" op (with full tombstone payload).
            await self._trigger_hook("on_update", {
                "value": tombstone, 
                "key": key, 
                "base_rev": base_rev, 
                "base_doc": old_item, 
                "optimistic": optimistic
            })


        
    async def get_all_keys(self):
        return await self.db.query_engine.get_all_keys(self.name)
        
    async def clear(self, silent: bool = False, optimistic: bool = False):
        # If we are in an overlay, we should force optimistic behavior
        if self._overlay.active:
             optimistic = True
             
        # If we have an active overlay or we need hooks, we must be granular
        if self._overlay.active or not silent:
             # Get all keys from DB
             db_keys = await self.get_all_keys()
             
             # Also get keys from overlay (in case of optimistic adds not yet in IDB)
             overlay_keys = set()
             if self._overlay.active:
                 overlay_keys = {k for k, op in self._overlay.mutations.items() if op['type'] in ('add', 'put')}
             
             all_keys = set(db_keys) | overlay_keys
             
             for key in all_keys:
                  await self.delete(key, silent=silent, optimistic=optimistic)
             return
             
        # Bulk clear (Fast path - only if silent and no overlay)
        res = await self.db.query_engine.clear(self.name)
        self._set_version(self._version.peek() + 1)
        return res

    def drop(self):
        if not self.db._db_instance:
             raise IndexedDBError("Database instance not available for drop()")
        self.db._db_instance.deleteObjectStore(self.name)

    async def update(self, key: Any, changes: Union[Dict[str, Any], Callable[[Dict[str, Any]], None]], silent: bool = False, optimistic: bool = False):

        obj = await self.get(key)
        original_obj_was_none = obj is None
        
        if obj is None:
             if isinstance(changes, dict):

                 obj = changes
             else:
                 raise IndexedDBError(f"Key {key} not found in {self.name} and cannot upsert with callable")
        else:
            if callable(changes):
                changes(obj) 
            else:
                obj.update(changes)
        

        try:
            await self.put(obj, silent=silent, optimistic=optimistic)
        except StorageError as e:
            # If we were attempting an Upsert (original obj was None) and validation failed,
            # it likely means the user expected a partial update on an existing record.
            if original_obj_was_none:
                 raise StorageError(f"Update failed: Record with key '{key}' not found, and partial data insufficient for new record. Details: {e}")
            raise e
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

    async def exhume(self) -> int:
        """
        Permanently removes all tombstone (deleted) records from the table.
        Returns the number of records that were exhumed.
        """
        if not self.db._db_instance:
            await self.db._ensure_open()

        # Create a collection filtered for tombstones and delete them all at once
        collection = self.filter(lambda record: record.get("_deleted") or record.get("deleted"))
        deleted_count = await collection.delete()

        return deleted_count

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
        self._order_by = None
        self._reverse = False
        self._filter_fn = None
        self._include_deleted = False
    
    def _add_condition(self, index, op, value):
        self._conditions.append({"index": index, "op": op, "value": value})

    def include_deleted(self):
        self._include_deleted = True
        return self

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
