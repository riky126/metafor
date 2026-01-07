import json
import time
import asyncio
import inspect
import contextvars
from typing import Any, Dict, Optional, Protocol, Callable, List, TypeVar, Generic, Union
from pyodide.ffi import create_proxy, JsProxy, to_js, JsException
from js import console, Object, Promise

from metafor.utils.runtime import is_server_side

if is_server_side:
    session_storage = None
    local_storage = None
    indexedDB = None
else:
    from js import localStorage, sessionStorage, indexedDB

# --- Common Exceptions ---

class StorageError(Exception):
    """Base exception for storage-related errors."""
    pass

class IndexedDBError(StorageError):
    """Exception raised for IndexedDB specific errors."""
    pass

class IndexedDBError(StorageError):
    """Exception raised for IndexedDB specific errors."""
    pass

# --- Transaction Context ---
_current_transaction_var = contextvars.ContextVar("current_transaction", default=None)

# --- Helper Utilities ---

async def _js_promise_to_future(js_promise):
    """Converts a JavaScript Promise to an asyncio Future."""
    future = asyncio.Future()

    def resolve(value):
        try:
            # Unwrap JsProxy if possible/needed, but usually result is JS object
            # For data coming back from IDB, we often want it as Python dict if possible
            py_value = value.to_py() if hasattr(value, 'to_py') else value
            future.set_result(py_value)
        except Exception as e:
            future.set_result(value)

    def reject(error):
        err_msg = str(error)
        if hasattr(error, 'name') and hasattr(error, 'message'):
            err_msg = f"{error.name}: {error.message}"
        future.set_exception(IndexedDBError(err_msg))

    js_promise.then(create_proxy(resolve)).catch(create_proxy(reject))
    return await future

def _to_js_obj(data):
    """Helper to convert Python dict to JS Object safely."""
    return to_js(data, dict_converter=Object.fromEntries)

# --- Dexie-like Implementation ---

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
        """Iterates over the results and calls fn for each item."""
        items = await self.to_array()
        for item in items:
            res = fn(item)
            if inspect.iscoroutine(res):
                await res
    
    async def to_array(self) -> List[Dict[str, Any]]:
        return await self.table._execute_query(self)

    async def first(self) -> Optional[Dict[str, Any]]:
        # If no explicit limit set, optimization: limit 1
        original_limit = self._limit
        self._limit = 1
        results = await self.to_array()
        self._limit = original_limit # Restore?
        return results[0] if results else None
        
    async def count(self) -> int:
         # Optimization: use count() request instead of getAll
         # For now, implemented via to_array len which respects filters/limits
         results = await self.to_array()
         return len(results)

class Table:
    def __init__(self, name: str, db: 'Indexie', primary_key: str = None):
        self.name = name
        self.db = db
        self.primary_key = primary_key
        
    async def add(self, item: Dict[str, Any], key: Any = None):
        return await self.db._execute_rw(self.name, lambda store: store.add(_to_js_obj(item), key) if key else store.add(_to_js_obj(item)))
        
    async def put(self, item: Dict[str, Any], key: Any = None):
        return await self.db._execute_rw(self.name, lambda store: store.put(_to_js_obj(item), key) if key else store.put(_to_js_obj(item)))
        
    async def get(self, key: Any):
        return await self.db._execute_ro(self.name, lambda store: store.get(key))
        
    async def delete(self, key: Any):
        return await self.db._execute_rw(self.name, lambda store: store.delete(key))
        
    async def clear(self):
         return await self.db._execute_rw(self.name, lambda store: store.clear())


    async def update(self, key: Any, changes: Dict[str, Any]):
        """Performs a partial update on an object."""
        obj = await self.get(key)
        if obj is None:
             raise IndexedDBError(f"Key {key} not found in {self.name}")
        
        # Merge changes
        obj.update(changes)
        
        # Put back
        await self.put(obj)
        return True

    async def to_array(self):
        return await self.db._execute_ro(self.name, lambda store: store.getAll())
        
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

    async def _execute_query(self, collection: Collection):
        """Executes a query based on the Collection definition."""
        
        # We process each condition separately and merge results (Union).
        # OR logic in IDB usually means multiple queries.
        
        all_results_dict = {} # Deduplication map: pk -> item
        
        conditions = collection._conditions
        if not conditions:
            # Fallback for empty condition? getAll()
            conditions = [{"index": ":primary", "op": None, "value": None}] # Treat as full scan

        for cond in conditions:
            index = cond.get("index")
            op = cond.get("op")
            value = cond.get("value")
            
            # Inner query logic for a single condition
            def query_logic(store):
                target = store
                index_used = None
                
                # Decide usage of index
                if index and index != ":id" and index != ":primary": 
                     if store.indexNames.contains(index):
                         target = store.index(index)
                         index_used = index
                
                # If explicit orderBy matches this condition's index usage, good.
                # But with OR queries, we can't rely on native sort usually unless only 1 condition.
                
                key_range = None
                from js import IDBKeyRange
                
                if op == "equals":
                    key_range = IDBKeyRange.only(value)
                elif op == "above":
                    key_range = IDBKeyRange.lowerBound(value, True)
                elif op == "below":
                    key_range = IDBKeyRange.upperBound(value, True)
                elif op == "starts_with":
                     val = value
                     next_val = val[:-1] + chr(ord(val[-1]) + 1)
                     key_range = IDBKeyRange.bound(val, next_val, False, True)
                
                # Optimization for native limit only if 1 condition and other checks pass
                # Complex with OR. Disable native limit for OR queries for correctness (simple union).
                # Only use native limit if 1 condition and no filter.
                
                can_use_native_limit = False
                native_limit_count = None
                
                if len(conditions) == 1 and collection._filter_fn is None and not collection._reverse:
                     if collection._limit is not None:
                         native_limit_count = collection._limit + collection._offset
                         can_use_native_limit = True

                # Check sort compatibility for single condition
                if can_use_native_limit and collection._order_by:
                    if index_used != collection._order_by:
                        can_use_native_limit = False

                # Execution
                req = None
                if can_use_native_limit and native_limit_count is not None:
                     if key_range:
                         req = target.getAll(key_range, native_limit_count)
                     else:
                         req = target.getAll(None, native_limit_count)
                else:
                     if key_range:
                         req = target.getAll(key_range)
                     else:
                         req = target.getAll()
                         
                return req

            # Execute this condition
            batch_results = await self.db._execute_ro(self.name, query_logic)
            
            # Merge into all_results
            pk_key = self.primary_key if self.primary_key else "id" # Default assumption
            
            for item in batch_results:
                # We need to extract the PK to dedupe.
                # If item is dict, use item[pk]. If it's primitive?
                pk_val = item.get(pk_key)
                if pk_val is not None:
                    # check unique
                    if pk_val not in all_results_dict:
                        all_results_dict[pk_val] = item
                else:
                    # fallback if no PK found? Just append? IDB implies objects have keys.
                    # If out of band keys? We only support inline keys usually.
                    pass

        results = list(all_results_dict.values())
        
        # Post-processing in Python
        # 1. Memory Sort
        if collection._order_by:
             try:
                 results.sort(key=lambda x: x.get(collection._order_by))
             except:
                 pass # Key might be missing
        
        # 1.5 Reverse if needed
        if collection._reverse:
            results.reverse()

        # 2. Filter
        if collection._filter_fn:
            results = [x for x in results if collection._filter_fn(x)]

        # 3. Offset and Limit
        
        # Apply offset
        if collection._offset > 0:
            if len(results) > collection._offset:
                results = results[collection._offset:]
            else:
                results = []
                
        # Apply limit
        if collection._limit is not None:
             if len(results) > collection._limit:
                 results = results[:collection._limit]
                 
        return results


class Version:
    def __init__(self, db, version_number):
        self.db = db
        self.version_number = version_number
        self.schema_definitions = {}

    def stores(self, schema: Dict[str, str]):
        self.schema_definitions = schema
        self.db._register_version(self)
        return self


class Indexie:
    def __init__(self, name: str, db: 'Indexie' = None): # db arg for compatibility if needed, though usually just name
        self.name = name
        self._versions: List[Version] = []
        self._db_instance = None
        self._tables: Dict[str, Table] = {}
        self._is_open = False
        
    def version(self, v: int) -> Version:
        ver = Version(self, v)
        return ver

    def _register_version(self, version: Version):
        self._versions.append(version)
        # Register tables immediately to allow access before open()
        for table_name in version.schema_definitions.keys():
             if table_name not in self._tables:
                 # Extract PK
                 schema_str = version.schema_definitions[table_name]
                 args = [x.strip() for x in schema_str.split(',')]
                 pk_def = args[0]
                 key_path = pk_def
                 if pk_def.startswith("++"):
                     key_path = pk_def[2:]
                 elif pk_def.startswith("&"):
                     key_path = pk_def[1:]

                 self._tables[table_name] = Table(table_name, self, primary_key=key_path)

    def __getattr__(self, name):
        if name in self._tables:
            return self._tables[name]
        raise AttributeError(f"'Indexie' object has no attribute '{name}'")
        
    def table(self, name):
        return self._tables.get(name)

    async def transaction(self, mode: str, scopes: Union[str, List[str]], async_fn: Callable):
        """
        Executes an async function within a single transaction.
        mode: "rw" (readwrite) or "r" (readonly)
        scopes: list of table names involved
        async_fn: async function to execute
        """
        if isinstance(scopes, str):
            scopes = [scopes]
            
        idb_mode = "readwrite" if mode == "rw" or mode == "readwrite" else "readonly"
        
        db = await self._ensure_open()
        txn = db.transaction(to_js(scopes), idb_mode)
        
        # Set context
        token = _current_transaction_var.set(txn)
        
        try:
            # We await the user function.
            # Dexie/IDB caveats: The transaction commits when no requests are pending in EL.
            # Awaiting Python futures that tick the loop might cause commit if no IDB requests are active?
            # Pyodide/JS bridging generally keeps txn alive if we await JS promises derived from it.
            # But if we await pure python sleep, it might close.
            # Users must ensure they chain IDB calls.
            
            res = await async_fn()
            return res
        except Exception as e:
            # Abort if error
            try:
                txn.abort()
            except:
                pass
            raise e
        finally:
             _current_transaction_var.reset(token)

    async def open(self):
        if self._is_open:
            return self
            
        if not self._versions:
             raise IndexedDBError("No versions defined for Dexie DB")
             
        # Sort versions to find latest
        # current logic just takes the max version definition
        latest_version = max(self._versions, key=lambda v: v.version_number)
        
        req = indexedDB.open(self.name, latest_version.version_number)
        
        future = asyncio.Future()

        def on_upgrade(event):
            db = event.target.result
            txn = event.target.transaction
            
            current_ver_num = event.oldVersion
            new_ver_num = event.newVersion
            
            console.log(f"Indexie: Upgrading {self.name} from {current_ver_num} to {new_ver_num}")

            # Find versions to apply
            for ver in sorted(self._versions, key=lambda v: v.version_number):
                if ver.version_number > current_ver_num:
                    self._apply_schema(db, txn, ver.schema_definitions)

        def on_success(event):
            self._db_instance = event.target.result
            self._is_open = True
            console.log(f"Indexie: Opened {self.name} v{self._db_instance.version}")
            future.set_result(self)

        def on_error(event):
            err = event.target.error
            console.error("Indexie Open Error:", err)
            future.set_exception(IndexedDBError(str(err)))

        req.onupgradeneeded = create_proxy(on_upgrade)
        req.onsuccess = create_proxy(on_success)
        req.onerror = create_proxy(on_error)
        
        return await future

    def _apply_schema(self, db, txn, schema):
        for table_name, schema_str in schema.items():
            # Check if store exists
            store = None
            if db.objectStoreNames.contains(table_name):
                 # For now, minimal support: get store from txn
                 store = txn.objectStore(table_name)
                 # Real Dexie diffs indexes and updates them.
                 # Simplified: clear indexes and recreate? Or just add missing?
                 # Implementation complexity limit: We will delete and recreate if it exists for drastic changes, 
                 # or try to migrate.
                 # Safest simplified approach: if it exists, assume it matches or leave it be.
                 # BUT, strict Dexie behavior tries to match schema.
                 # Let's iterate schema string to ensure indexes exists.
                 pass
            else:
                # Parse primary key
                args = [x.strip() for x in schema_str.split(',')]
                pk_def = args[0]
                props = {}
                key_path = pk_def
                
                # Handling ++ (autoIncrement)
                if pk_def.startswith("++"):
                    props['autoIncrement'] = True
                    key_path = pk_def[2:]
                else:
                    props['autoIncrement'] = False
                
                # Handling & (unique) - technically unique is an index trait, not PK trait usually in Dexie string 
                # unless it is the first arg?
                # Dexie: "++id, name, age" -> PK is id, autoInc.
                # Dexie: "id, name" -> PK is id.
                
                props['keyPath'] = key_path
                
                store = db.createObjectStore(table_name, _to_js_obj(props))
                
                # Create indexes
                for idx_def in args[1:]:
                    if not idx_def: continue
                    
                    unique = False
                    multi = False
                    src = idx_def
                    
                    if src.startswith('&'):
                        unique = True
                        src = src[1:]
                    elif src.startswith('*'):
                        multi = True
                        src = src[1:]
                        
                    store.createIndex(src, src, _to_js_obj({"unique": unique, "multiEntry": multi}))


    # --- Internal Transaction Execution ---
    
    async def _ensure_open(self):
        if not self._is_open:
            await self.open()
        return self._db_instance

    async def _execute_rw(self, store_name, op):
        return await self._execute(store_name, "readwrite", op)

    async def _execute_ro(self, store_name, op):
        return await self._execute(store_name, "readonly", op)

    async def _execute(self, store_name, mode, op):
        
        # Check for active transaction
        active_txn = _current_transaction_var.get()
        
        if active_txn:
             # Verify scope? for performance we might skip or check objectStoreNames
             # Simple check:
             if active_txn.objectStoreNames.contains(store_name):
                 if mode == "readwrite" and active_txn.mode == "readonly":
                      raise IndexedDBError(f"Cannot execute readwrite on {store_name} inside readonly transaction")
                 
                 store = active_txn.objectStore(store_name)
                 result_from_op = op(store)
                 
                 # Common logic extraction
                 if isinstance(result_from_op, tuple):
                     req = result_from_op[0]
                 else:
                     req = result_from_op

                 if hasattr(req, 'onsuccess'):
                     # We must return a future that awaits this request primarily
                     future = asyncio.Future()
                     def success(e):
                        res = e.target.result
                        if hasattr(res, 'to_py'): res = res.to_py()
                        future.set_result(res)
                     def error(e):
                        future.set_exception(IndexedDBError(str(e.target.error)))
                        
                     req.onsuccess = create_proxy(success)
                     req.onerror = create_proxy(error)
                     return await future
                 return req

        # Fallback to auto-committed transaction (default behavior)
        db = await self._ensure_open()
        txn = db.transaction(store_name, mode)
        store = txn.objectStore(store_name)
        
        
        # op might return a tuple if we modified it in _execute_query logic?
        # _execute_query returns await self.db._execute_ro(...)
        # query_logic returns req. _execute_ro awaits request.
        
        result_from_op = op(store)
        
        # Handle case where op returns a tuple (req, metadata)
        # But _execute_ro expects a Request-like object to attach events?
        # We need to unpack if needed or store metadata elsewhere?
        # Actually _execute_query implementation above returned (req, need_memory_sort) inside query_logic?
        # NO, query_logic must return the IDBRequest object for _execute to attach listeners.
        # If I want to pass metadata out, I should use a nonlocal or mutable arg.
        
        # Let's fix _execute_query logic to not return tuple in query_logic.
        
        if isinstance(result_from_op, tuple):
             # This block is just conceptual safety, query_logic must return req
             req = result_from_op[0]
        else:
             req = result_from_op
        
        # If it's a request (IDBRequest), await it.
        # If it's void (like delete?) strictly speaking delete returns IDBRequest.
        # Some calls might fail if not IDBRequest.
        
        if hasattr(req, 'onsuccess'):
            future = asyncio.Future()
            
            def success(e):
                res = e.target.result
                # Auto-convert generic results
                if hasattr(res, 'to_py'):
                     res = res.to_py()
                # If the op returned a tuple (req, extra_info), handle it? 
                # No, op() returns the Request object directly usually.
                future.set_result(res)
                
            def error(e):
                future.set_exception(IndexedDBError(str(e.target.error)))
                
            req.onsuccess = create_proxy(success)
            req.onerror = create_proxy(error)
            
            return await future
        return req


# --- Browser Storage Helpers (Keep existing) ---

class MemoryStorage:
    """In-memory storage engine implementation."""
    def __init__(self):
        self._storage: Dict[str, Any] = {}
    def save(self, key: str, data: Any, expires: Optional[int] = None) -> None:
        self._storage[key] = data
    def load(self, key: str) -> Optional[Any]:
        return self._storage.get(key)
    def remove(self, key: str, attr_key: Optional[str] = None) -> None:
        if attr_key:
            data = self.load(key)
            if isinstance(data, dict) and attr_key in data:
                del data[attr_key]
                self.save(key, data)
        elif key in self._storage:
             del self._storage[key]
    def clear(self, key: str) -> None:
        if key in self._storage:
            del self._storage[key]

class BrowserStorage:
    def __init__(self, storage_target, description):
        if is_server_side:
             self._storage = MemoryStorage()
             self.description = f"{description} (Memory Fallback)"
        elif storage_target:
            self._storage = storage_target
            self.description = description
        else:
             self._storage = MemoryStorage()
             self.description = f"{description} (Memory Fallback - Target Missing)"

    def save(self, key: str, data: Any, expires: Optional[int] = None) -> None:
        if isinstance(self._storage, MemoryStorage):
             self._storage.save(key, data, expires)
             return
        try:
            value_to_store = {"data": data}
            if expires:
                value_to_store["expires"] = time.time() + expires
            self._storage.setItem(key, json.dumps(value_to_store))
        except Exception as e:
            raise StorageError(f"Error saving to {self.description}: {e}") from e

    def load(self, key: str) -> Optional[Any]:
        if isinstance(self._storage, MemoryStorage):
            return self._storage.load(key)
        try:
            value_json = self._storage.getItem(key)
            if value_json:
                value = json.loads(value_json)
                if "expires" in value and value["expires"] is not None:
                    if value["expires"] < time.time():
                        self.clear(key) 
                        return None
                return value.get("data") 
            return None
        except json.JSONDecodeError as e:
            console.warn(f"Could not decode JSON from {self.description} for key '{key}'. Clearing item.")
            self.clear(key)
            return None
        except Exception as e:
            raise StorageError(f"Error loading from {self.description}: {e}") from e

    def remove(self, key: str, attr_key: Optional[str] = None) -> None:
        if isinstance(self._storage, MemoryStorage):
             self._storage.remove(key, attr_key)
             return
        if attr_key:
            data = self.load(key)
            if isinstance(data, dict) and attr_key in data:
                del data[attr_key]
                value_json = self._storage.getItem(key)
                expires = None
                if value_json:
                    try:
                        original_value = json.loads(value_json)
                        expires = original_value.get("expires")
                    except json.JSONDecodeError:
                        pass 
                self.save(key, data, expires=(expires - time.time()) if expires else None)
        else:
            self.clear(key)

    def clear(self, key: str):
        if isinstance(self._storage, MemoryStorage):
            self._storage.clear(key)
            return
        try:
            self._storage.removeItem(key)
        except Exception as e:
            raise StorageError(f"Error clearing key '{key}' from {self.description}: {e}") from e

_session_storage_target = None if is_server_side else sessionStorage
_local_storage_target = None if is_server_side else localStorage

session_storage = BrowserStorage(_session_storage_target, "session_storage")
local_storage = BrowserStorage(_local_storage_target, "local_storage")