
import asyncio
import json
import inspect
import urllib.parse
import hashlib
import time
from typing import Any, Dict, Optional
from js import console, Object, Promise, JSON, fetch
from pyodide.ffi import create_proxy, to_js

from metafor.channels.server_push import ServerPush
from metafor.http.client import Http

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

# --- Revision Tracking Utilities ---

def _generate_revision(doc: Dict[str, Any], parent_rev: Optional[str] = None) -> str:
    """
    Generate a generation-based revision string (CouchDB style).
    Format: "{generation}-{hash}"
    """
    # Create deterministic hash from content
    # Exclude revision and metadata fields
    doc_copy = {k: v for k, v in doc.items() 
                if not k.startswith('_') or k == '_id'}
    doc_str = json.dumps(doc_copy, sort_keys=True)
    
    try:
        hash_obj = hashlib.md5(doc_str.encode())
        doc_hash = hash_obj.hexdigest()
    except Exception:
        # Fallback hash
        hash_val = abs(hash(doc_str))
        doc_hash = hex(hash_val)[2:]

    # Calculate generation
    generation = 1
    if parent_rev:
        try:
            parts = parent_rev.split('-')
            if len(parts) >= 2 and parts[0].isdigit():
                generation = int(parts[0]) + 1
        except Exception:
            pass
            
    return f"{generation}-{doc_hash}"

def _get_revision(doc: Dict[str, Any]) -> Optional[str]:
    """Get the revision from a document, or None if not present."""
    return doc.get("_rev")

def _set_revision(doc: Dict[str, Any], rev: Optional[str] = None, parent_rev: Optional[str] = None) -> str:
    """Set or generate a revision for a document. Returns the revision."""
    if rev is None:
        rev = _generate_revision(doc, parent_rev)
    doc["_rev"] = rev
    doc["_lastModified"] = time.time() * 1000
    return rev

def _ensure_revision(doc: Dict[str, Any]) -> str:
    """Ensure a document has a revision. Returns the revision."""
    if "_rev" not in doc:
        return _set_revision(doc)
    return doc["_rev"]

# --- Sync Logic ---

class Support:
    @staticmethod
    async def sync_electric(table, url: str, params: dict = None, headers: dict = None, http_client = None):
        """
        Starts syncing this table with an ElectricSQL Shape.
        """
        
        # --- Phase 1: Initial Fetch (Snapshot) ---
        query_params = (params or {}).copy()
        
        console.log(f"Phase 1: Fetching Snapshot from {url}")
        
        offset = "-1"
        data = None
        fetch_headers = None
        
        try:
            if http_client:
                 # Use provided HTTP client
                 # dict return: {'data': ..., 'headers': ..., 'status': ...}
                 response_dict = await http_client.get(url, params=query_params, headers=headers)
                 
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
                 
                 text_method = getattr(response, 'text', None)
                 json_method = getattr(response, 'json', None)
                 
                 data = []
                 if text_method:
                     raw_text = await text_method()
                     try:
                         if not raw_text.strip().startswith("data:"):
                             data = json.loads(raw_text)
                         else:
                             data = raw_text
                     except:
                         data = raw_text
                 elif json_method:
                      try:
                          res = json_method()
                          if inspect.isawaitable(res) or isinstance(res, Promise):
                              data = await res
                          else:
                              data = res
                      except Exception:
                          data = "[]" 

            # Extract Offset
            handle_header = None
            cursor_header = None
            if fetch_headers:
                header_offset = None
                
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
                    return k.split("/")[-1].strip('"')
                return k
            
            if py_data:
                if isinstance(py_data, str):
                    clean_data = py_data.strip()
                    if clean_data.startswith("data:"):
                        clean_data = clean_data[5:].strip()
                    
                    try:
                        py_data = json.loads(clean_data)
                    except Exception:
                         console.error(f"Could not parse snapshot string: {clean_data[:100]}...")
                         return

                # --- Debug: Check if we have a wrapper ---
                if isinstance(py_data, dict):
                    # Check if it looks like the response object itself
                    if "data" in py_data and "status" in py_data:
                         console.warn("Snapshot Data appears to be wrapped in response object. Extracting 'data'.")
                         py_data = py_data["data"]
                         # Re-parse if it's a string now
                         if isinstance(py_data, str):
                            clean_data = py_data.strip()
                            if clean_data.startswith("data:"):
                                clean_data = clean_data[5:].strip()
                            try:
                                py_data = json.loads(clean_data)
                            except Exception:
                                console.error(f"Could not parse inner snapshot string: {clean_data[:100]}...")
                                return

                console.log(f"Snapshot Data Received: {py_data}")
                console.log(f"Applying {len(py_data)} items from snapshot...")
                for item in py_data:
                     headers = item.get("headers") if isinstance(item, dict) and "headers" in item else {}
                     if headers and headers.get("control"):
                         continue
                     
                     val = item.get("value") if isinstance(item, dict) and "value" in item else item
                     
                     if val is item and isinstance(val, dict):
                         if "headers" in val or "key" in val:
                             val = val.copy()
                             val.pop("headers", None)
                             val.pop("key", None)
                     
                     if val is None:
                         continue

                     key = item.get("key") if isinstance(item, dict) and "key" in item else None
                     clean_key = _get_clean_key(key)
                     await table.put(val, key=clean_key, silent=True)
                     
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
        
        server_push = ServerPush(sse_url)
        table._server_push = server_push # Store ref on table
        
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
                            
                        try:
                            key = change.get("key")
                            value = change.get("value")
                            headers = change.get("headers") or {}
                            
                            if headers.get("control"):
                                continue
                                
                            op = headers.get("operation")
                            deleted = change.get("deleted") or op == "delete"
                            
                            clean_key = _get_clean_key(key)
                            
                            if deleted:
                                await table.delete(clean_key, silent=True)
                            elif op == "update":
                                await table.update(clean_key, value, silent=True)
                            elif value is not None:
                                await table.put(value, key=clean_key, silent=True)
                                
                        except Exception as inner_e:
                            console.error(f"Error processing SSE change: {inner_e}")
                            continue

            except Exception as e:
                console.error(f"SSE Message Error: {str(e)}")

        server_push.on_message(on_sse_message)
        server_push.connect()
