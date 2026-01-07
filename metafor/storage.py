import json
import time
import asyncio
import inspect
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
    def __init__(self, table, index: str):
        self.table = table
        self.index = index
        
    def equals(self, value):
        return Collection(self.table, self.index, "equals", value)
        
    def above(self, value):
        return Collection(self.table, self.index, "above", value)
    
    def below(self, value):
        return Collection(self.table, self.index, "below", value)
        
    def startsWith(self, value):
        return Collection(self.table, self.index, "startsWith", value)


class Collection:
    def __init__(self, table, index, op, value):
        self.table = table
        self.index = index
        self.op = op
        self.value = value
    
    async def toArray(self) -> List[Dict[str, Any]]:
        return await self.table._execute_query(self)

    async def first(self) -> Optional[Dict[str, Any]]:
        results = await self.toArray()
        return results[0] if results else None
        
    async def count(self) -> int:
         # Optimization: use count() request instead of getAll
         # For now, implemented via toArray len
         results = await self.toArray()
         return len(results)

class Table:
    def __init__(self, name: str, db: 'Indexie'):
        self.name = name
        self.db = db
        
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

    async def toArray(self):
        return await self.db._execute_ro(self.name, lambda store: store.getAll())
        
    def where(self, index: str):
        return WhereClause(self, index)

    async def _execute_query(self, collection: Collection):
        """Executes a query based on the Collection definition."""
        # Using IDBKeyRange for filtering
        def query_logic(store):
            target = store
            if collection.index and collection.index != ":id": # :id convention for primary key if needed, else assumed primary if not index
                 if store.indexNames.contains(collection.index):
                     target = store.index(collection.index)
                 else:
                     # Fallback or error? Dexie implicitly uses primary key if index name matches? 
                     # For simplicity, assume valid index name provided or primary key name
                     pass

            key_range = None
            from js import IDBKeyRange
            
            if collection.op == "equals":
                key_range = IDBKeyRange.only(collection.value)
            elif collection.op == "above":
                key_range = IDBKeyRange.lowerBound(collection.value, True)
            elif collection.op == "below":
                key_range = IDBKeyRange.upperBound(collection.value, True)
            elif collection.op == "startsWith":
                 # startsWith "A" -> lower "A", upper "B" (next char)
                 val = collection.value
                 next_val = val[:-1] + chr(ord(val[-1]) + 1)
                 key_range = IDBKeyRange.bound(val, next_val, False, True)
            
            if key_range:
                return target.getAll(key_range)
            else:
                return target.getAll()

        return await self.db._execute_ro(self.name, query_logic)


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
                 self._tables[table_name] = Table(table_name, self)

    def __getattr__(self, name):
        if name in self._tables:
            return self._tables[name]
        raise AttributeError(f"'Indexie' object has no attribute '{name}'")
        
    def table(self, name):
        return self._tables.get(name)

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
        db = await self._ensure_open()
        txn = db.transaction(store_name, mode)
        store = txn.objectStore(store_name)
        
        req = op(store)
        
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