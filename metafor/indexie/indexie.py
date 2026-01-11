
import asyncio
import contextvars
import inspect
from typing import Any, Dict, List, Optional, Union, Callable
from js import console, indexedDB
from pyodide.ffi import create_proxy, to_js

from .plugin import Table, Version
from .query_engine import QueryEngine
from .support import IndexedDBError, _to_js_obj

# --- Transaction Context ---
_current_transaction_var = contextvars.ContextVar("current_transaction", default=None)

class Indexie:
    class Mode:
        READ_WRITE = "rw"
        READ_ONLY = "r"

    def __init__(self, name: str, db: 'Indexie' = None): 
        self.name = name
        self._versions: List[Version] = []
        self._db_instance = None
        self._tables: Dict[str, Table] = {}
        self._is_open = False
        self.query_engine = QueryEngine(self)
        self.sync_manager = None
        
    def enable_sync(self, upstream_url: str, pull_enabled: bool = True, 
                    conflict_handler: Optional[Callable] = None,
                    conflict_strategy: str = "last_write_wins"):
        """
        Enable synchronization with conflict resolution.
        
        Args:
            upstream_url: Backend sync endpoint URL
            pull_enabled: Whether to enable pull replication (default: True)
            conflict_handler: Custom conflict resolution function (optional)
            conflict_strategy: Conflict resolution strategy. Options:
                - "last_write_wins" (default): Use document with latest timestamp
                - "local_wins": Always keep local version
                - "remote_wins": Always accept remote version
                - "merge": Merge both documents (remote takes precedence)
                - "custom": Use conflict_handler function
        """
        from .sync import SyncManager, OfflineQueue, ReplicationState, ConflictHistory
        self.sync_manager = SyncManager(
            self, 
            upstream_url, 
            pull_enabled=pull_enabled,
            conflict_handler=conflict_handler,
            conflict_strategy=conflict_strategy
        )
        
        # Register system tables so they are accessible via db.table(...) if needed, 
        # and so hooks don't try to attach to them (SyncManager handles exclusion but good to have them tracked)
        self._tables[OfflineQueue.TABLE_NAME] = self.sync_manager.queue.table
        self._tables[ReplicationState.TABLE_NAME] = self.sync_manager.state.table
        self._tables[ConflictHistory.TABLE_NAME] = self.sync_manager.conflict_history.table
        
        if self._is_open:
             self.sync_manager.start()
             
        return self

    def version(self, v: int) -> Version:
        ver = Version(self, v)
        return ver

    def _register_version(self, version: Version):
        self._versions.append(version)
        # Register tables immediately
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
        
        if self._db_instance and self._db_instance.objectStoreNames.contains(name):
             return Table(name, self)

        raise AttributeError(f"'Indexie' object has no attribute '{name}'")
        
    def table(self, name):
        return self._tables.get(name)

    async def transaction(self, mode: str, scopes: Union[str, List[str]], async_fn: Callable):
        if isinstance(scopes, str):
            scopes = [scopes]
            
        idb_mode = "readwrite" if mode == "rw" or mode == "readwrite" else "readonly"
        
        db = await self._ensure_open()
        txn = db.transaction(to_js(scopes), idb_mode)
        
        token = _current_transaction_var.set(txn)
        
        try:
            res = await async_fn()
            return res
        except Exception as e:
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
             
        latest_version = max(self._versions, key=lambda v: v.version_number)
        
        req = indexedDB.open(self.name, latest_version.version_number)
        
        future = asyncio.Future()

        def on_upgrade(event):
            db = event.target.result
            txn = event.target.transaction
            
            current_ver_num = event.oldVersion
            new_ver_num = event.newVersion
            
            console.log(f"Indexie: Upgrading {self.name} from {current_ver_num} to {new_ver_num}")

            self._db_instance = db
            
            token = _current_transaction_var.set(txn)
            try:
                for ver in sorted(self._versions, key=lambda v: v.version_number):
                    if ver.version_number > current_ver_num:
                        self._apply_schema(db, txn, ver.schema_definitions)
                        if ver.upgrade_callback:
                             res = ver.upgrade_callback(txn)
                             if inspect.iscoroutine(res):
                                 asyncio.create_task(res)
                
                # Check for Sync Tables
                if self.sync_manager:
                     self._ensure_sync_tables(db, txn)

            finally:
                _current_transaction_var.reset(token)

        def on_success(event):
            self._db_instance = event.target.result
            self._is_open = True
            console.log(f"Indexie: Opened {self.name} v{self._db_instance.version}")
            
            if self.sync_manager:
                self.sync_manager.start()
                
            future.set_result(self)

        def on_error(event):
            err = event.target.error
            console.error("Indexie Open Error:", err)
            future.set_exception(IndexedDBError(str(err)))

        req.onupgradeneeded = create_proxy(on_upgrade)
        req.onsuccess = create_proxy(on_success)
        req.onerror = create_proxy(on_error)
        
        return await future

    def _ensure_sync_tables(self, db, txn):
        from .sync import ConflictHistory
        
        # Create _sys_sync_queue (id, timestamp index)
        if not db.objectStoreNames.contains("_sys_sync_queue"):
            console.log("Indexie: Creating _sys_sync_queue")
            store = db.createObjectStore("_sys_sync_queue", _to_js_obj({"keyPath": "id"}))
            store.createIndex("timestamp", "timestamp", _to_js_obj({"unique": False}))

        if not db.objectStoreNames.contains("_sys_sync_state"):
            console.log("Indexie: Creating _sys_sync_state")
            store = db.createObjectStore("_sys_sync_state", _to_js_obj({"keyPath": "id"}))

        if not db.objectStoreNames.contains(ConflictHistory.TABLE_NAME):
            console.log(f"Indexie: Creating {ConflictHistory.TABLE_NAME}")
            store = db.createObjectStore(ConflictHistory.TABLE_NAME, _to_js_obj({"keyPath": "id"}))
            store.createIndex("timestamp", "timestamp", _to_js_obj({"unique": False}))
            store.createIndex("table", "table", _to_js_obj({"unique": False}))

    def _apply_schema(self, db, txn, schema):
        for table_name, schema_str in schema.items():
            store = None
            if db.objectStoreNames.contains(table_name):
                 store = txn.objectStore(table_name)
            else:
                args = [x.strip() for x in schema_str.split(',')]
                pk_def = args[0]
                props = {}
                key_path = pk_def
                
                if pk_def.startswith("++"):
                    props['autoIncrement'] = True
                    key_path = pk_def[2:]
                else:
                    props['autoIncrement'] = False
                
                props['keyPath'] = key_path
                
                store = db.createObjectStore(table_name, _to_js_obj(props))
                
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

    async def _ensure_open(self):
        if not self._is_open:
            await self.open()
        return self._db_instance

    async def _execute_rw(self, store_name, op):
        return await self._execute(store_name, "readwrite", op)

    async def _execute_ro(self, store_name, op):
        return await self._execute(store_name, "readonly", op)

    async def _execute(self, store_name, mode, op):
        active_txn = _current_transaction_var.get()
        
        if active_txn:
             if active_txn.objectStoreNames.contains(store_name):
                 is_ro = active_txn.mode == "readonly"
                 
                 if mode == "readwrite" and is_ro:
                      raise IndexedDBError(f"Cannot execute readwrite on {store_name} inside readonly transaction")
                 
                 store = active_txn.objectStore(store_name)
                 result_from_op = op(store)
                 
                 req = result_from_op
                 if isinstance(req, tuple): req = req[0]

                 if hasattr(req, 'onsuccess'):
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

        db = await self._ensure_open()
        txn = db.transaction(store_name, mode)
        store = txn.objectStore(store_name)
        
        result_from_op = op(store)
        
        req = result_from_op
        if isinstance(req, tuple): req = req[0]
        
        if hasattr(req, 'onsuccess'):
            future = asyncio.Future()
            
            def success(e):
                try:
                    res = e.target.result
                    if hasattr(res, 'to_py'):
                         res = res.to_py()
                    future.set_result(res)
                except Exception as ex:
                    console.error(f"IDB Success Callback Error: {ex}")
                    if not future.done():
                        future.set_exception(ex)
                
            def error(e):
                try:
                    err_msg = str(e.target.error) if e.target and e.target.error else "Unknown IDB Error"
                    if not future.done():
                        future.set_exception(IndexedDBError(err_msg))
                except Exception as ex:
                    console.error(f"IDB Error Callback Error: {ex}")
                    if not future.done():
                        future.set_exception(ex)
                
            req._onsuccess_proxy = create_proxy(success)
            req._onerror_proxy = create_proxy(error)
            
            req.onsuccess = req._onsuccess_proxy
            req.onerror = req._onerror_proxy
            
            try:
                return await future
            finally:
                req._onsuccess_proxy.destroy()
                req._onerror_proxy.destroy()
                
        return req
