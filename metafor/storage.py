import json
import time
import asyncio
import inspect
import contextvars
from typing import Any, Dict, Optional, Protocol, Callable, List, TypeVar, Generic, Union
import urllib.parse
from metafor.core import create_signal
from pyodide.ffi import create_proxy, JsProxy, to_js, JsException
from js import console, Object, Promise, JSON, fetch
from metafor.channels.server_push import ServerPush
from metafor.http.client import Http

import contextlib # New import
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
    
    def to_array(self) -> List[Dict[str, Any]]:
        self.table._version() # Track dependency
        # return self.table._execute_query(self)
        async def _call_execute_query():
             return await self.table._execute_query(self)
        return _call_execute_query()

    def first(self) -> Optional[Dict[str, Any]]:
        # Sync wrapper returning coroutine
        self.table._version() # Track dependency
        
        async def _run():
            # If no explicit limit set, optimization: limit 1
            original_limit = self._limit
            self._limit = 1
            results = await self.to_array()
            self._limit = original_limit 
            return results[0] if results else None
            
        return _run()
        
    def count(self) -> int:
         self.table._version()
         async def _run():
             # Optimization: use count() request instead of getAll
             # For now, implemented via to_array len which respects filters/limits
             results = await self.to_array()
             return len(results)
         return _run()

class HookRegistrar:
    def __init__(self):
        self._hooks = {}

    def on_add(self, callback: Callable):
        self._register("on_add", callback)

    def on_update(self, callback: Callable):
        self._register("on_update", callback)

    def on_delete(self, callback: Callable):
        self._register("on_delete", callback)

    def _register(self, event: str, callback: Callable):
        if event not in self._hooks:
            self._hooks[event] = []
        self._hooks[event].append(callback)

    async def _trigger(self, event: str, payload: Any):
        if event in self._hooks:
            for cb in self._hooks[event]:
                res = cb(payload)
                if inspect.iscoroutine(res):
                    await res
                    
class OverlayLayer:
    """In-memory layer for optimistic transactions."""
    def __init__(self, table: 'Table'):
        self.table = table
        self.mutations: Dict[Any, Dict[str, Any]] = {} # key -> {type: "put"|"delete", value: ...}
        self.active = False
        self.visible = True # If False, mutations are buffered but not shown in queries
        
    def add(self, item: Dict[str, Any], key: Any = None):
        if not key:
            # Need a temp key. If PK in item, use it. Else auto-gen?
            # For overlay, auto-inc keys are tough. We might need negative keys or UUIDs.
            # Assuming key provided or in item for now.
            if self.table.primary_key in item:
                key = item[self.table.primary_key]
            else:
                # Fallback temp key (negative random?)
                import random
                key = -random.randint(1, 1000000)
                item[self.table.primary_key] = key
        
        self.mutations[key] = {"type": "put", "value": item}
        return key
        
    def put(self, item: Dict[str, Any], key: Any = None):
        pk = key or item.get(self.table.primary_key)
        if not pk:
             # Similar temp key logic
             import random
             pk = -random.randint(1, 1000000)
             item[self.table.primary_key] = pk
             
        self.mutations[pk] = {"type": "put", "value": item}
        return pk
        
    def delete(self, key: Any):
        self.mutations[key] = {"type": "delete"}
        
    def clear(self):
        self.mutations.clear()
        # Mark as clear all? Complex. For now, simple clear of pending.
        
    async def commit(self):
        """Persist changes to IDB."""
        # Disable overlay so table.put/delete writes to IDB
        self.active = False
        try:
             # Batch apply
             keys = list(self.mutations.keys())
             for key in keys:
                 op = self.mutations[key]
                 if op["type"] == "put":
                     # Check for temporary key (negative integer)
                     is_temp_key = isinstance(key, int) and key < 0
                     
                     if is_temp_key and self.table.primary_key:
                         # Strip temp key so IDB generates real one (assuming auto-inc)
                         val = op["value"].copy()
                         if self.table.primary_key in val:
                             del val[self.table.primary_key]
                         await self.table.put(val, silent=True)
                     else:
                         await self.table.put(op["value"], key=key, silent=True)
                         
                 elif op["type"] == "delete":
                     await self.table.delete(key, silent=True)
             
             self.mutations.clear()
        except Exception as e:
             # If commit fails, re-enable overlay to keep optimistic state accessible?
             # Or arguably, the transaction failed.
             self.active = True
             raise e

    async def rollback(self):
        self.mutations.clear()
        self.active = False
        if self.visible:
             self.table._set_version(self.table._version.peek() + 1) # Trigger UI refresh to clear optimistic data
        self.visible = True # Reset default



from enum import Enum

class Strategy(Enum):
    LOCAL_FIRST = "local_first"
    NETWORK_FIRST = "network_first"

class Table:
    def __init__(self, name: str, db: 'Indexie', primary_key: str = None, strategy: Strategy = Strategy.LOCAL_FIRST):
        self.name = name
        self.db = db
        self.primary_key = primary_key
        self.strategy = strategy
        # Signal to track table version for reactivity
        self._version, self._set_version = create_signal(0)
        self._hook_registrar = HookRegistrar()
        self._overlay = OverlayLayer(self) # New Overlay
        
        
    @contextlib.asynccontextmanager
    async def start_transaction(self, optimistic: bool = False):
        """
        Starts a transaction.
        :param optimistic: If True, writes are visible immediately (Optimistic UI). 
                           If False, writes are buffered and only visible on commit (Standard ACID).
        """
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
        
    @property
    def hook(self):
        return self._hook_registrar
        
    async def _trigger_hook(self, event: str, payload: Any):
        await self._hook_registrar._trigger(event, payload)
        
    async def add(self, item: Dict[str, Any], key: Any = None, silent: bool = False):
        # 1. Check Overlay
        if self._overlay.active:
             res = self._overlay.add(item, key)
             
             if self._overlay.visible:
                 self._set_version(self._version.peek() + 1)
                 # Still trigger hooks? Yes, to allow side-effects
                 if not silent:
                     await self._trigger_hook("on_add", {"item": item, "key": res})
             return res

        use_explicit_key = key is not None and self.primary_key is None
        
        # If inline key is expected but missing in item and provided in key, inject it
        if self.primary_key and key is not None and self.primary_key not in item:
             item[self.primary_key] = key

        if self.strategy == Strategy.NETWORK_FIRST and not silent:
            # Network First: Hook -> Local
            # For 'add', key might be unknown if auto-increment.
            # We pass key=None or User-provided key.
            await self._trigger_hook("on_add", {"item": item, "key": key})
            
            # If hook didn't throw, proceed to write
            res = await self.db._execute_rw(self.name, lambda store: store.add(_to_js_obj(item), key) if use_explicit_key else store.add(_to_js_obj(item)))
            self._set_version(self._version.peek() + 1)
            return res
        else:
            # Local First (Default): Local -> Hook
            res = await self.db._execute_rw(self.name, lambda store: store.add(_to_js_obj(item), key) if use_explicit_key else store.add(_to_js_obj(item)))
            self._set_version(self._version.peek() + 1)
            if not silent:
                await self._trigger_hook("on_add", {"item": item, "key": res})
            return res
        
    async def put(self, item: Dict[str, Any], key: Any = None, silent: bool = False):
        pk_val = key or item.get(self.primary_key)
        
        # 1. Overlay
        if self._overlay.active:
             res = self._overlay.put(item, key)
             
             if self._overlay.visible:
                 self._set_version(self._version.peek() + 1)
                 if not silent:
                     await self._trigger_hook("on_update", {"item": item, "key": res})
             return res
        
        use_explicit_key = key is not None and self.primary_key is None
        
        # If inline key is expected but missing in item and provided in key, inject it
        # This handles updates where key is passed separately
        if self.primary_key and key is not None: 
             item[self.primary_key] = key

        if self.strategy == Strategy.NETWORK_FIRST and not silent:
            await self._trigger_hook("on_update", {"item": item, "key": pk_val})
            
            res = await self.db._execute_rw(self.name, lambda store: store.put(_to_js_obj(item), key) if use_explicit_key else store.put(_to_js_obj(item)))
            self._set_version(self._version.peek() + 1)
            return res
        else:
            res = await self.db._execute_rw(self.name, lambda store: store.put(_to_js_obj(item), key) if use_explicit_key else store.put(_to_js_obj(item)))
            self._set_version(self._version.peek() + 1)
            if not silent:
                await self._trigger_hook("on_update", {"item": item, "key": pk_val})
            return res
        
    def get(self, key: Any):
        self._version() # Track dependency
        
        async def _run():
            # 1. Check Overlay
            if self._overlay.active and self._overlay.visible:
                 if key in self._overlay.mutations:
                     op = self._overlay.mutations[key]
                     if op['type'] == 'delete':
                         return None
                     return op['value']
            
            return await self.db._execute_ro(self.name, lambda store: store.get(key))
        return _run()
        
    async def delete(self, key: Any, silent: bool = False):
        # 1. Overlay
        # 1. Overlay
        if self._overlay.active:
             self._overlay.delete(key)
             if self._overlay.visible:
                 self._set_version(self._version.peek() + 1)
                 if not silent:
                      await self._trigger_hook("on_delete", {"key": key, "all": False})
             return
             
        if self.strategy == Strategy.NETWORK_FIRST and not silent:
             await self._trigger_hook("on_delete", {"key": key, "all": False})
             
             res = await self.db._execute_rw(self.name, lambda store: store.delete(key))
             self._set_version(self._version.peek() + 1)
             return res
        else:
            res = await self.db._execute_rw(self.name, lambda store: store.delete(key))
            self._set_version(self._version.peek() + 1)
            if not silent:
                await self._trigger_hook("on_delete", {"key": key, "all": False})
            return res
        
    async def clear(self, silent: bool = False):
         res = await self.db._execute_rw(self.name, lambda store: store.clear())
         self._set_version(self._version.peek() + 1)
         # Clear usually doesn't need specific item hooks, but if we had on_clear:
         # if not silent: await self._trigger_hook("on_clear", {})
         return res

    def drop(self):
        """Deletes the object store. Only valid during an upgrade hook."""
        if not self.db._db_instance:
             raise IndexedDBError("Database instance not available for drop()")
        self.db._db_instance.deleteObjectStore(self.name)


    async def update(self, key: Any, changes: Union[Dict[str, Any], Callable[[Dict[str, Any]], None]], silent: bool = False):
        """
        Performs a partial update on an object.
        Supports functional updates: await db.users.update(key, lambda u: u.update(changes))
        """
        obj = await self.get(key)
        
        if obj is None:
             console.log(f"Table.update: Key {key} not found. Changes type: {type(changes)}")
             if isinstance(changes, dict):
                 obj = changes
                 # If key is part of changes, good. If not, and we have key arg, we might need to ensure it.
                 # But self.put will handle the key extraction or usage.
             else:
                 raise IndexedDBError(f"Key {key} not found in {self.name} and cannot upsert with callable")
        else:
            # Apply changes
            if callable(changes):
                changes(obj) 
            else:
                obj.update(changes)
        
        # Put back
        await self.put(obj, silent=silent) 
        # put() will trigger on_update and increment version
        return True

    async def sync_electric(self, url: str, params: Dict[str, Any] = None, headers: Dict[str, str] = None, http_client: Optional[Http] = None):
        """
        Starts syncing this table with an ElectricSQL Shape.
        Phase 1: Initial Fetch (Snapshot) via HTTP GET.
        Phase 2: Live Updates via ServerPush (SSE).
        
        Args:
            url: The sync endpoint URL.
            params: Query parameters (e.g. {"table": "users"}).
            headers: Headers to include in the snapshot request (e.g. Authorization).
            http_client: Optional 'metafor.http.client.Http' instance. If provided, it will be used
                         for the snapshot fetch, allowing use of interceptors.
        """
        
        # --- Phase 1: Initial Fetch (Snapshot) ---
        query_params = (params or {}).copy()
        
        console.log(f"Phase 1: Fetching Snapshot from {url}")
        
        offset = "-1"
        data = None
        fetch_headers = None
        
        try:
            if http_client:
                 # Use provided HTTP client (supports interceptors)
                 # dict return: {'data': ..., 'headers': ..., 'status': ...}
                 response_dict = await http_client.get(url, params=query_params, headers=headers)
                 
                 # Check status (http_client usually throws on error unless configured otherwise, 
                 # but let's check status just in case)
                 if 200 <= response_dict['status'] < 300:
                     data = response_dict.get('data')
                     fetch_headers = response_dict.get('headers')
                 else:
                     console.error(f"Snapshot HTTP Client Error: {response_dict['status']}")
                     return
            else:
                 # Fallback to standard fetch
                 snapshot_url = f"{url}?{urllib.parse.urlencode(query_params)}"
                 fetch_opts = {}
                 if headers:
                     fetch_opts['headers'] = to_js(headers)
                     
                 response = await fetch(snapshot_url, **fetch_opts)

                 if not response.ok:
                     console.error(f"Snapshot Fetch Error: {response.status if hasattr(response, 'status') else 'Unknown'}")
                     return

                 fetch_headers = getattr(response, 'headers', {})
                 
                 # Robust body reading: try text first to handle "data: ..." format
                 text_method = getattr(response, 'text', None)
                 json_method = getattr(response, 'json', None)
                 
                 data = []
                 if text_method:
                     raw_text = await text_method()
                     # If it looks like JSON, try to parse. If it fails or looks like SSE "data:", keep as string
                     try:
                         # Only parse if it doesn't look like SSE
                         if not raw_text.strip().startswith("data:"):
                             data = json.loads(raw_text)
                         else:
                             data = raw_text
                     except:
                         data = raw_text
                 elif json_method:
                      # Fallback if text() not available (unlikely for fetch)
                      try:
                          res = json_method()
                          if inspect.isawaitable(res) or isinstance(res, Promise):
                              data = await res
                          else:
                              data = res
                      except Exception:
                          data = "[]" # Error parsing JSON

            # Extract Offset
            handle_header = None
            cursor_header = None
            if fetch_headers:
                header_offset = None
                
                # Robust extraction
                get_header = getattr(fetch_headers, 'get', None)
                if not get_header and isinstance(fetch_headers, dict):
                    get_header = fetch_headers.get
                
                if get_header:
                    handle_header = get_header("electric-handle") or get_header("Electric-Handle")
                    header_offset = get_header("electric-offset") or get_header("Electric-Offset")
                    cursor_header = get_header("electric-cursor") or get_header("Electric-Cursor")
                    
                if header_offset:
                    offset = header_offset

                console.log(f"fetch_headers: {fetch_headers}")

            # Convert to Python
            py_data = data.to_py() if hasattr(data, 'to_py') else data
            
            def _get_clean_key(k):
                if isinstance(k, str) and "/" in k:
                    # Handle ElectricSQL composite key: "public"."users"/"uuid"
                    # We want the UUID part
                    return k.split("/")[-1].strip('"')
                return k
            
            if py_data:
                # If it's a string, parse it
                if isinstance(py_data, str):
                    # Handle SSE format: "data: <json>"
                    clean_data = py_data.strip()
                    if clean_data.startswith("data:"):
                        clean_data = clean_data[5:].strip()
                    
                    try:
                        py_data = json.loads(clean_data)
                    except Exception:
                         console.error(f"Could not parse snapshot string: {clean_data[:100]}...")
                         return

                console.log(f"Snapshot Data Received: {py_data}")
                console.log(f"Applying {len(py_data)} items from snapshot...")
                for item in py_data:
                     # Check for headers/control messages first
                     headers = item.get("headers") if isinstance(item, dict) and "headers" in item else {}
                     if headers and headers.get("control"):
                         continue
                     
                     val = item.get("value") if isinstance(item, dict) and "value" in item else item
                     
                     # Safety: If we fell back to 'item', ensure we don't store wrapper fields
                     if val is item and isinstance(val, dict):
                         # If it looks like a wrapper (has headers/key), clean it
                         if "headers" in val or "key" in val:
                             val = val.copy()
                             val.pop("headers", None)
                             val.pop("key", None)
                     
                     if val is None:
                         continue

                     key = item.get("key") if isinstance(item, dict) and "key" in item else None
                     clean_key = _get_clean_key(key)
                     await self.put(val, key=clean_key, silent=True)
                     
            console.log(f"Snapshot applied. Starting SSE from offset {offset}.")

        except Exception as e:
            console.error(f"Snapshot Failed: {e}")
            return

        # --- Phase 2: Live Updates (ServerPush) ---
        sse_params = query_params.copy()
        sse_params["live"] = "true"
        sse_params["offset"] = offset
        
        if handle_header:
            sse_params["handle"] = handle_header
        
        if cursor_header:
            sse_params["cursor"] = cursor_header
        
        sse_url = f"{url}?{urllib.parse.urlencode(sse_params)}"
        
        # Use ServerPush abstraction
        self._server_push = ServerPush(sse_url)
        
        # Define handler
        async def on_sse_message(event):
            console.log(f"SSE Message Received: {event.data}")
            try:
                if not event.data: return
                data = JSON.parse(event.data)
                py_changes = data.to_py() if hasattr(data, 'to_py') else data
                console.log(f"Live Update Data Received: {py_changes}")
                
                if isinstance(py_changes, dict): py_changes = [py_changes]
                
                if py_changes:
                    for change in py_changes:
                        if change is None:
                            console.log("Found explicitly None change, skipping.")
                            continue
                            
                        # console.log(f"Processing change: {change}, type: {type(change)}")
                        
                        try:
                            key = change.get("key")
                            value = change.get("value")
                            headers = change.get("headers") or {}
                            
                            # Skip control messages (e.g. up-to-date markers)
                            if headers.get("control"):
                                continue
                                
                            op = headers.get("operation")
                            deleted = change.get("deleted") or op == "delete"
                            
                            clean_key = _get_clean_key(key)
                            
                            if deleted:
                                await self.delete(clean_key, silent=True)
                            elif op == "update":
                                await self.update(clean_key, value, silent=True)
                            elif value is not None:
                                await self.put(value, key=clean_key, silent=True)
                                
                        except Exception as inner_e:
                            console.error(f"Error processing SSE change: {inner_e}")
                            # console.error(f"Change: {change}") # Keep concise unless debugging
                            continue

            except Exception as e:
                console.error(f"SSE Message Error: {str(e)}")

        # Register and Connect
        self._server_push.on_message(on_sse_message)
        self._server_push.connect()

    def to_array(self):
        # Delegate to Collection to ensure overlay logic in _execute_query is used
        # Must be sync to capture signal dependency immediately
        return Collection(self, None).to_array()
        
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
        
        # Optimization Strategy:
        # Check if we can use a native cursor (single index usage + native sort).
        # We can use native cursor if:
        # 1. Single condition (or no condition)
        # 2. Sorting by the SAME index as the condition (or no specific condition index)
        # 3. No complex Python filtering (collection._filter_fn is None) - actually we can filter in loop, but efficiency varies.
        #    If specific filter fn exists, we still benefit from not allocating ALL rows if we can stream, 
        #    but we can't skip readily.
        
        conditions = collection._conditions
        order_by = collection._order_by
        reverse = collection._reverse
        limit = collection._limit
        offset = collection._offset
        filter_fn = collection._filter_fn
        
        # Default condition if empty
        if not conditions:
            conditions = [{"index": ":primary", "op": None, "value": None}]

        # Check for Native Cursor Compatibility
        use_native_cursor = False
        target_index = None
        target_range_op = None
        target_range_val = None
        
        # Only support native cursor strategy for single condition currently
        if len(conditions) == 1:
            cond = conditions[0]
            cond_index = cond.get("index")
            
            # Determine the index we will iterate on
            # If we have an explicit Order By, we MUST rely on that index for the cursor direction.
            # If we also have a Where clause on a DIFFERENT index, we cannot do this natively (requires compound index).
            
            if order_by:
                # We are forcing an order.
                if cond_index in [":primary", ":id", None] or cond_index == order_by:
                     # Sorting by the same thing we are filtering (or filtering all). Good.
                     use_native_cursor = True
                     target_index = order_by 
                     target_range_op = cond.get("op")
                     target_range_val = cond.get("value")
                else:
                     # Sorting by A, Filtering by B -> Cannot use native sorted cursor for B without scanning all.
                     # Fallback to old "Fetch All & Sort in Memory" method.
                     use_native_cursor = False
            else:
                # No specific order requested. We can iterate using the condition's index naturally.
                use_native_cursor = True
                target_index = cond_index
                target_range_op = cond.get("op")
                target_range_val = cond.get("value")

            # One edge case: count() might be optimized separately, but here we are in to_array() path.

        if use_native_cursor:
            # --- Native Cursor Execution Path ---
            
            def cursor_logic(store):
                # 1. Determine Target (Store vs Index)
                target = store
                if target_index and target_index not in [":primary", ":id"]:
                    if store.indexNames.contains(target_index):
                        target = store.index(target_index)
                    else:
                        # Fallback if index missing? Should error.
                        pass
                
                # 2. Determine Range
                key_range = None
                from js import IDBKeyRange
                
                # Helper for range creation (same as before)
                if target_range_op == "equals":
                    key_range = IDBKeyRange.only(target_range_val)
                elif target_range_op == "above":
                    key_range = IDBKeyRange.lowerBound(target_range_val, True)
                elif target_range_op == "below":
                    key_range = IDBKeyRange.upperBound(target_range_val, True)
                elif target_range_op == "starts_with":
                     val = target_range_val
                     next_val = val[:-1] + chr(ord(val[-1]) + 1)
                     key_range = IDBKeyRange.bound(val, next_val, False, True)
                
                # 3. Determine Direction
                direction = "prev" if reverse else "next"
                
                # 4. Open Cursor
                # We need to use openCursor. It returns a request.
                # However, processing the cursor is event-based (onsuccess called multiple times).
                # _execute_ro expects a Promise/Future/Request returning a SINGLE result.
                # We cannot just return the request here because generic _execute wrapper expects 
                # a request that resolves to a *value* (like getAll), or we must handle the cursor *inside* 
                # this logic but we are in the JS realm? 
                
                # Problem: _execute logic assumes a single-shot request.
                # We need to wrap the cursor iteration in a Promise or handle it here and return a list.
                # Since we are inside the 'op' callback of _execute, we can do complex things if we return a Promise.
                
                promise = Promise.new(create_proxy(lambda resolve, reject: _process_cursor(
                    target, key_range, direction, offset, limit, filter_fn, resolve, reject
                )))
                
                return promise

            # Helper defined OUTSIDE to be safe, or INSIDE? 
            # Needs to be available to the proxy.
            def _process_cursor(target, key_range, direction, offset_param, limit_param, filter_fn_param, resolve, reject):
                results = []
                # Mutable state for stepping
                state = {
                    "advanced": False, 
                    "count": 0,       # Number of items collected
                    "skipped": 0      # Number of items skipped (for clean offset)
                }
                
                has_filter = filter_fn_param is not None
                
                # Optimization: Can we use native advance?
                # Only if NO filter is applied. If filter is applied, we must check items before skipping/counting.
                can_use_native_advance = (offset_param > 0) and (not has_filter)
                
                req = target.openCursor(key_range, direction)
                
                def on_success(e):
                    cursor = e.target.result
                    if cursor:
                        # 1. Handle Native Offset (Fast Skip)
                        if can_use_native_advance and not state["advanced"]:
                            state["advanced"] = True
                            cursor.advance(offset_param)
                            return # Wait for next success
                        
                        # 2. Get Item
                        item = cursor.value
                        
                        should_include = True
                        if has_filter:
                             # Must convert
                             py_item = item.to_py() if hasattr(item, 'to_py') else item
                             if not filter_fn_param(py_item):
                                 should_include = False
                             else:
                                 # Optimization: Use the py_item we already converted
                                 item = py_item
                        
                        # 3. Handle Manual Offset (Slow Skip - used if filter exists)
                        if should_include and not can_use_native_advance and offset_param > 0:
                            if state["skipped"] < offset_param:
                                state["skipped"] += 1
                                should_include = False # Skip this one, it's valid but before offset
                        
                        if should_include:
                            if not has_filter: # If we didn't convert yet
                                 item = item.to_py() if hasattr(item, 'to_py') else item
                                 
                            results.append(item)
                            state["count"] += 1
                            
                            # 4. Check Limit
                            if limit_param is not None and state["count"] >= limit_param:
                                resolve(to_js(results)) # Done
                                return

                        cursor.continue_()
                    else:
                        # End of cursor
                        resolve(to_js(results))
                
                def on_error(e):
                     reject(e.target.error)

                req.onsuccess = create_proxy(on_success)
                req.onerror = create_proxy(on_error)


            # EXECUTE THE CURSOR LOGIC
            # Note: _execute_ro logic unwraps promises.
            batch_results = await self.db._execute_ro(self.name, cursor_logic)
            
            # The result might be a JS Promise (thenable) because cursor_logic returns a Promise,
            # and _execute_ro returns it as-is (it only automatically awaits IDBRequests).
            if hasattr(batch_results, 'then'):
                batch_results = await batch_results
            
            # Convert JS Array Proxy to Python list
            if hasattr(batch_results, 'to_py'):
                 batch_results = batch_results.to_py()
            
            # Ensure it is a list (fallback safety)
            if not isinstance(batch_results, list):
                 try:
                     batch_results = list(batch_results)
                 except:
                     pass # Should be list now if to_py worked, or if it was already a list.
                     
            # Overlay Logic (must still apply merge for optimistic UI)
            # Simplistic Merge: The cursor stream missed optimistic updates that are NOT in IDB yet.
            # And it might include items that are effectively deleted in Overlay.
            # We must apply Overlay changes to this result set.
             
            # ... (Overlay merge code reuse needed) ...
            results = batch_results # Already a list

        else:
            # --- Legacy Fallback Path (Fetch All + Sort in Memory) ---
            # This handles complex OR queries or mismatched Sort/Filter
            
            all_results_dict = {} 
            
            for cond in conditions:
                index = cond.get("index")
                op = cond.get("op")
                value = cond.get("value")
                
                def query_logic_legacy(store):
                    target = store
                    from js import IDBKeyRange
                    
                    if index and index not in [":primary", ":id"]: 
                         if store.indexNames.contains(index):
                             target = store.index(index)
                    
                    key_range = None
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
                    
                    if key_range:
                         return target.getAll(key_range)
                    else:
                         return target.getAll()
                
                batch = await self.db._execute_ro(self.name, query_logic_legacy)
                
                pk_key = self.primary_key if self.primary_key else "id"
                for item in batch:
                    pk_val = item.get(pk_key)
                    if pk_val is not None:
                        if pk_val not in all_results_dict:
                            all_results_dict[pk_val] = item
                            
            results = list(all_results_dict.values())
            
            # Legacy In-Memory Sorting & Pagination
            if order_by:
                 try:
                     results.sort(key=lambda x: x.get(order_by))
                 except: pass
            
            if reverse:
                results.reverse()

            if filter_fn:
                results = [x for x in results if filter_fn(x)]

            if offset > 0:
                results = results[offset:] if len(results) > offset else []

            if limit is not None:
                 results = results[:limit]


        # --- Common Overlay Merge (Post-Fetch) ---
        # Whether cursor or legacy, we need to respect the Overlay.
        # Note for Cursor: If we paginated, the overlay might inject items that *should* be generally appear.
        # Correct paging with optimistic updates is hard (requires knowing where they fit).
        # We appply overlay *after* fetching page. This implies the page might grow > limit, 
        # or include items that shouldn't be there (deleted).
        
        if self._overlay.active and self._overlay.visible:
             pk = self.primary_key
             
             # Apply Deletes
             deleted_keys = {k for k, v in self._overlay.mutations.items() if v['type'] == 'delete'}
             if deleted_keys:
                 results = [r for r in results if r.get(pk) not in deleted_keys]

             # Apply Puts
             # Issue: For cursor pagination, we might have skipped items that are now modified?
             # Or we might have a new item that belongs in this page?
             # Basic approach: Just ensure all local puts are potentially added/merged if they match criteria.
             # This is "good enough" for simple optimistic UI.
             
             for key, op in self._overlay.mutations.items():
                 if op['type'] == 'put':
                      val = op['value']
                      
                      # Check if it matches filter/conditions
                      # (Simplification: We assume if it's in overlay it might be valid, 
                      # real logic requires re-evaluating where logic in python)
                      
                      # Merge/Replace
                      existing_idx = -1
                      for i, r in enumerate(results):
                           if r.get(pk) == key:
                               existing_idx = i
                               break
                      
                      if existing_idx != -1:
                           results[existing_idx] = val
                      else:
                           # Add to results? 
                           # Only if we are not strictly paginating perfectly 
                           # or if it falls in the range?
                           # We add it, and let re-sorting handle it if needed.
                           results.append(val)
                           
             # Re-sort if we touched things (needed for optimistic puts)
             if order_by:
                 try:
                     results.sort(key=lambda x: x.get(order_by), reverse=reverse)
                 except: pass

        return results


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
        """Registers a callback to run when this version is applied."""
        self.upgrade_callback = fn
        return self


class Indexie:
    class Mode:
        READ_WRITE = "rw"
        READ_ONLY = "r"

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
        
        # Fallback: Check if table exists in active DB connection (e.g. during upgrade)
        if self._db_instance and self._db_instance.objectStoreNames.contains(name):
             return Table(name, self)

        raise AttributeError(f"'Indexie' object has no attribute '{name}'")
        
    def table(self, name):
        return self._tables.get(name)

    async def transaction(self, mode: str, scopes: Union[str, List[str]], async_fn: Callable):
        """
        Executes an async function within a single transaction.
        mode: Indexie.Mode.READ_WRITE ("rw") or Indexie.Mode.READ_ONLY ("r")
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
            # Find versions to apply
            # Upgrade transaction is special: it allows schema changes (createObjectStore)
            # and data manipulation (add/put) within the same transaction.
            
            # We must expose the db_instance for schema operations like drop() which use db.deleteObjectStore
            self._db_instance = db
            
            token = _current_transaction_var.set(txn)
            try:
                for ver in sorted(self._versions, key=lambda v: v.version_number):
                    if ver.version_number > current_ver_num:
                        self._apply_schema(db, txn, ver.schema_definitions)
                        if ver.upgrade_callback:
                             # Execute upgrade callback
                             res = ver.upgrade_callback(txn) # We pass txn, but helper methods use context var
                             if inspect.iscoroutine(res):
                                 # We cannot await easily in this sync callback
                                 asyncio.create_task(res)
            finally:
                _current_transaction_var.reset(token)
                # Should we unset self._db_instance? It will be set again in on_success. 
                # Leaving it might be fine, or safer to unset to avoid using half-open DB?
                # on_success comes right after usually.

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
                 # Allow write if mode is readwrite OR versionchange (upgrade transaction)
                 is_ro = active_txn.mode == "readonly"
                 # versionchange is effectively R/W + Schema
                 
                 if mode == "readwrite" and is_ro:
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
                try:
                    res = e.target.result
                    # Auto-convert generic results
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
                
            # Keep references to proxies to prevent GC
            req._onsuccess_proxy = create_proxy(success)
            req._onerror_proxy = create_proxy(error)
            
            req.onsuccess = req._onsuccess_proxy
            req.onerror = req._onerror_proxy
            
            try:
                return await future
            finally:
                # Cleanup proxies if needed? Usually attached to req is fine.
                # But req is short-lived.
                req._onsuccess_proxy.destroy()
                req._onerror_proxy.destroy()
                
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

def use_live_query(query_fn: Callable[[], Any]):
    """
    A hook that runs a query and keeps it updated when underlying tables change.
    Uses metafor's signal system (create_effect) to track dependencies.
    """
    from metafor.core import create_signal, create_effect, on_dispose
    import inspect
    
    # Initialize with empty list
    data, set_data = create_signal([])
    
    def run_query():
        try:
            # We execute query_fn synchronously to capture signal dependencies (Table._version())
            # Since Table methods now strictly track version before returning coroutine,
            # this works inside the effect.
            res = query_fn()
            
            if inspect.iscoroutine(res):
                # If it's a coroutine, we spawn a task to await it
                # The effect dependency is already tracked by the synchronous call above.
                async def _await_result():
                     try:
                         val = await res
                         set_data(val)
                     except Exception as e:
                         console.error(f"Live Query Async Error: {e}")
                
                asyncio.create_task(_await_result())
            else:
                # Synchronous result
                set_data(res)
                
        except Exception as e:
            console.error(f"Live Query Execution Error: {e}")

    # Create effect to track and rerun
    effect = create_effect(run_query)
    
    on_dispose(effect.dispose)
            
    return data