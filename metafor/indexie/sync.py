
import asyncio
import time
import uuid
import hashlib
import json
from typing import Any, Dict, List, Optional, Callable, Union
from js import console, navigator, window
from pyodide.ffi import create_proxy

from .plugin import Table, HookRegistrar
from .support import IndexedDBError, _to_js_obj, _generate_revision, _get_revision, _set_revision, _ensure_revision


# --- Conflict Resolution ---

class Conflict:
    """Represents a conflict between local and remote document versions."""
    
    def __init__(self, table_name: str, key: Any, local_doc: Dict[str, Any], 
                 remote_doc: Dict[str, Any], local_rev: str, remote_rev: str):
        self.table_name = table_name
        self.key = key
        self.local_doc = local_doc
        self.remote_doc = remote_doc
        self.local_rev = local_rev
        self.remote_rev = remote_rev
        self.timestamp = time.time() * 1000
        self.id = str(uuid.uuid4())
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "table": self.table_name,
            "key": self.key,
            "local_doc": self.local_doc,
            "remote_doc": self.remote_doc,
            "local_rev": self.local_rev,
            "remote_rev": self.remote_rev,
            "timestamp": self.timestamp
        }


class ConflictHistory:
    """Stores conflict history for inspection and debugging."""
    TABLE_NAME = "_sys_conflict_history"
    
    def __init__(self, db):
        self.db = db
        self.table = Table(self.TABLE_NAME, db, primary_key="id")
    
    async def record(self, conflict: Conflict):
        """Record a conflict for later inspection."""
        await self.table.add(conflict.to_dict())
    
    async def get_all(self) -> List[Dict[str, Any]]:
        """Get all recorded conflicts."""
        return await self.table.to_array()
    
    async def clear(self):
        """Clear conflict history."""
        await self.table.clear()


# --- Revision Tracking ---
# Moved to support.py

class OfflineQueue:
    TABLE_NAME = "_sys_sync_queue"

    def __init__(self, db, sync_manager: 'SyncManager' = None):
        self.db = db
        self.sync_manager = sync_manager
        # We need to ensure the table exists. 
        # For now, we assume it's created via schema injection in Indexie.
        self.table = Table(self.TABLE_NAME, db, primary_key="id")

    async def enqueue(self, table_name: str, op: str, key: Any, value: Any = None, base_rev: str = None, base_doc: dict = None):
        # Ensure value has a revision if it's a document
        if value and isinstance(value, dict) and op in ("put", "update"):
            _ensure_revision(value)
        
        # Optimization: Store Reference Only (State-Based Sync)
        stored_value = value
        if op in ("put", "update") and isinstance(value, dict):
             # Store reference to avoid duplication and ensure latest state is pushed
             stored_value = {
                 "ref_row": key
             }
        elif op == "delete":
             # Ensure delete_id is available in the value field for all sync hooks
             stored_value = {
                 "delete_id": key
             }
        
        # Check for existing pending mutation for this key (Coalescing)
        # Note: We look for the record ID inside value.ref_row since top-level 'key' is removed.
        items = await self.table.to_array()
        existing = next((i for i in items if i and i.get("table") == table_name and i.get("value", {}).get("ref_row") == key), None)
        
        if existing:
            # Update existing mutation (Coalesce)
            # We KEEP the original base_rev/base_doc (the start of the transaction)
            # We UPDATE the value to the latest
            existing["op"] = op
            existing["value"] = stored_value
            existing["timestamp"] = time.time() * 1000
            
            # If the original didn't have base info (e.g. was a create), and this one does?
            # If original was create (base=None), valid.
            # If original was update (base=X), and we update again (base=Y), we keep X!
            
            console.log(f"OfflineQueue: Coalesced {op} for {table_name}:{key}")
            await self.table.put(existing)
            
            # Trigger SyncManager global hooks
            if self.sync_manager:
                hook_name = "on_add" if op == "put" else "on_update" if op == "update" else "on_delete"
                await self.sync_manager.hook._trigger(hook_name, existing)
            return

        mutation = {
            "id": str(uuid.uuid4()),
            "table": table_name,
            "op": op,
            "value": stored_value,
            "timestamp": time.time() * 1000,
            "base_rev": base_rev,
            "base_doc": base_doc
        }
        console.log(f"OfflineQueue: Attempting to add mutation: {mutation}")
        await self.table.add(mutation)
        console.log(f"OfflineQueue: Enqueued {op} for {table_name}:{key}")
        
        # Trigger SyncManager global hooks
        if self.sync_manager:
            hook_name = "on_add" if op == "put" else "on_update" if op == "update" else "on_delete"
            await self.sync_manager.hook._trigger(hook_name, mutation)

    async def peek(self, limit=50) -> List[Dict[str, Any]]:
        # Order by timestamp. 
        # Since we use UUID keys, we might need a secondary index on timestamp or just sort in memory for now.
        # For simplicity in V1, we fetch all and sort. 
        # TODO: Add index on timestamp for performance.
        items = await self.table.to_array()
        items.sort(key=lambda x: x["timestamp"])
        return items[:limit]

    async def remove(self, ids: List[str]):
        # Batch delete
        for mid in ids:
            await self.table.delete(mid)

    async def count(self) -> int:
        return await self.table.count()


class ReplicationState:
    TABLE_NAME = "_sys_sync_state"
    
    def __init__(self, db):
        self.db = db
        self.table = Table(self.TABLE_NAME, db, primary_key="id")

    async def get_cursor(self) -> Optional[str]:
        rec = await self.table.get("cursor")
        return rec["value"] if rec else None

    async def set_cursor(self, cursor: str):
        await self.table.put({"id": "cursor", "value": cursor})


class SyncManager:
    # Conflict resolution strategies
    class ConflictStrategy:
        LAST_WRITE_WINS = "last_write_wins"
        LOCAL_WINS = "local_wins"
        REMOTE_WINS = "remote_wins"
        CUSTOM = "custom"
        MERGE = "merge"
    
    def __init__(self, db, upstream_url: str, push_interval: int = 5000, 
                 pull_enabled: bool = True, conflict_handler: Optional[Callable] = None,
                 conflict_strategy: str = ConflictStrategy.LAST_WRITE_WINS,
                 push_path: str = "/push", pull_path: str = "/pull",
                 http_client: Optional[Any] = None):
        self.db = db
        self.upstream_url = upstream_url.rstrip('/')
        self.push_interval = push_interval
        self.pull_enabled = pull_enabled
        self.conflict_handler = conflict_handler
        self.conflict_strategy = conflict_strategy
        self.push_path = push_path
        self.pull_path = pull_path
        self.http_client = http_client
        
        self.hook = HookRegistrar()
        self.queue = OfflineQueue(db, sync_manager=self)
        self.state = ReplicationState(db)
        self.conflict_history = ConflictHistory(db)
        
        self._is_online = navigator.onLine
        self._server_reachable = True # Assume reachable until proven otherwise? Or start False?
        # Let's start True if assume Online, but maybe better to ping on start.
        
        self._sync_task = None
        self._running = False

    @property
    def is_online(self) -> bool:
        # We are online only if browser is online AND server is reachable
        return self._is_online and self._server_reachable

    def _set_reachable(self, reachable: bool, error: str = None):
        if self._server_reachable != reachable:
            if reachable:
                console.log("SyncManager: Connection established with sync server")
            else:
                msg = f"SyncManager: {error} - Unable to reach sync server" if error else "SyncManager: Unable to reach sync server"
                console.warn(msg)
            self._server_reachable = reachable
        elif not reachable and error:
             # Even if already unreachable, if we have a new error during explicit check, maybe log it?
             # User asked for: "am seeing this message... the sync manager should print..."
             # If we silently ignore repeated errors, user might think check didn't run.
             # But we don't want to spam loop errors.
             # check_connection is explicit, so we might want to log there?
             # But for now let's stick to state change logging or specific error logging.
             pass

    async def check_connection(self) -> bool:
        """Explicitly check if the server is reachable."""
        try:
            # Use HEAD or GET to pull endpoint as lightweight check
            url = f"{self.upstream_url}{self.pull_path}"
            # Add timestamp to bypass cache
            url += f"?ping={int(time.time()*1000)}"
            
            if self.http_client:
                 resp_dict = await self.http_client.get(url)
                 if 200 <= resp_dict['status'] < 300:
                      self._set_reachable(True)
                      return True
                 else:
                      self._set_reachable(False, error=f"HTTP {resp_dict['status']}")
                      return False
            else:
                from js import fetch
                resp = await fetch(url, _to_js_obj({"method": "GET", "credentials": "include"}))
                
                if resp.ok:
                    self._set_reachable(True)
                    return True
                else:
                    self._set_reachable(False, error=f"HTTP {resp.status}")
                    return False
        except Exception as e:
            self._set_reachable(False, error=str(e))
            return False

    def start(self):
        self._running = True
        
        # Monitor Online/Offline
        self._setup_network_listeners()
        
        # Start Hooks
        self._attach_hooks()
        
        # Start Loop
        self._sync_task = asyncio.create_task(self._process_loop())
        console.log("SyncManager: Started")
        
        self._trigger_task = None

    def _trigger_push(self):
        """Schedule an immediate push (debounced)."""
        if not self._is_online or not self._server_reachable: return
        
        async def _run_push():
            await asyncio.sleep(0.5) # 500ms debounce
            await self._push()
            self._trigger_task = None
            
        if self._trigger_task:
            self._trigger_task.cancel()
            
        # We need a running loop
        try:
             loop = asyncio.get_event_loop()
             if loop.is_running():
                 self._trigger_task = loop.create_task(_run_push())
        except: pass

    def stop(self):
        self._running = False
        if self._sync_task:
            self._sync_task.cancel()

    def _setup_network_listeners(self):
        def on_online(e):
            console.log("SyncManager: Online")
            self._is_online = True
            # Trigger immediate sync check?

        def on_offline(e):
            console.log("SyncManager: Offline")
            self._is_online = False

        window.addEventListener("online", create_proxy(on_online))
        window.addEventListener("offline", create_proxy(on_offline))

    def _attach_hooks(self):
        # We need to iterate over all existing tables and attach hooks.
        # But this runs at startup, tables might be added dynamically?
        # Indexie should probably notify SyncManager when a table is created.
        # For now, we iterate what we have.
        
        # We need to exclude system tables!
        sys_tables = [OfflineQueue.TABLE_NAME, ReplicationState.TABLE_NAME, 
                     ConflictHistory.TABLE_NAME]

        for name, table in self.db._tables.items():
            if name in sys_tables: continue
            
            self._attach_table_hooks(name, table)

    def _attach_table_hooks(self, table_name, table):
        """Helper to capture table_name in closure correctly."""
        
        async def on_add(payload):
            await self._handle_hook_event(table_name, "add", payload)
        
        async def on_update(payload):
            await self._handle_hook_event(table_name, "update", payload)
            
        async def on_delete(payload):
            await self._handle_hook_event(table_name, "delete", payload)

        # Guard against double-attaching to the same table object
        if hasattr(table.hook, "_sync_attached"):
            return
        table.hook._sync_attached = True
        
        table.hook.on_add(on_add, priority_invoke=True)
        table.hook.on_update(on_update, priority_invoke=True)
        table.hook.on_delete(on_delete, priority_invoke=True)
        
        console.log(f"SyncManager: Attached hooks to {table_name}")

    async def _handle_hook_event(self, table_name: str, event_type: str, payload: Dict[str, Any]):
        """Unified handler for table hooks."""
        # Unify item/value access (Supports unified 'value' key, fallback to 'item')
        item = payload.get("value", payload.get("item"))
        if item: item = item.copy()
        
        key = payload.get("key")
        base_rev = payload.get("base_rev")
        base_doc = payload.get("base_doc")
        optimistic = payload.get("optimistic", False)
        
        if optimistic:
            # Ensure revision metadata is set on the item
            if item and isinstance(item, dict):
                # If key (primary key value) is available but not in item, inject it
                # to match the user's example where 'id': 4 is inside value
                table_obj = self.db._tables.get(table_name)
                pk = table_obj.primary_key if table_obj else None
                if pk and pk not in item and key:
                    item[pk] = key
                _ensure_revision(item)
            
            # Mutation timestamps
            now = time.time() * 1000
            
            # Manual Sync Path: Construct mutation data but don't enqueue/push
            mutation = {
                "id": str(uuid.uuid4()),
                "table": table_name,
                "op": "put" if event_type == "add" else ("update" if event_type == "update" else "delete"),
                # For put/add, value is the full document. 
                # For delete, use the user-requested {delete_id: key} format.
                "value": item if event_type in ("add", "update") else {"delete_id": key},
                "timestamp": now,
                # Top-level metadata for conflict resolution and manual sync
                "_rev": base_rev, 
                "base_doc": base_doc,
                "_lastModified": int(now + 1),
                "all": payload.get("all", False) # Pass through bulk flag if any
            }
            
            # Trigger global SyncManager hooks
            hook_name = f"on_{event_type}"
            await self.hook._trigger(hook_name, mutation)
            
            # Clear and Replace original payload to ensure clean mutation structure for listeners
            payload.clear()
            payload.update(mutation)
            return

        # Automatic Sync Path (Existing logic)
        if event_type == "add":
            if item:
                _ensure_revision(item)
            await self.queue.enqueue(table_name, "put", key, item, base_rev=base_rev, base_doc=base_doc)
        elif event_type == "update":
            if item:
                _ensure_revision(item)
            await self.queue.enqueue(table_name, "update", key, item, base_rev=base_rev, base_doc=base_doc)
        else:
            await self.queue.enqueue(table_name, "delete", key, base_rev=base_rev, base_doc=base_doc)
            
        self._trigger_push()

    async def _process_loop(self):
        while self._running:
            if self._is_online:
                # If we think we are online but server marked unreachable, try to ping
                if not self._server_reachable:
                    await self.check_connection()
                
                # If confirmed reachable (or optimistically true), proceed
                if self._server_reachable:
                    await self._push()
                    if self.pull_enabled:
                        await self._pull()
            
            await asyncio.sleep(self.push_interval / 1000)

    async def _pull(self):
        try:
            cursor = await self.state.get_cursor()
            
            # Construct URL
            url = f"{self.upstream_url}{self.pull_path}"
            if cursor:
                url += f"?checkpoint={cursor}"
                
            if self.http_client:
                 try:
                     resp_dict = await self.http_client.get(url)
                 except Exception as inner_e:
                     console.error(f"SyncManager: http_client.get failed: {inner_e!r}")
                     raise inner_e
                 
                 if not (200 <= resp_dict['status'] < 300):
                      console.warn(f"SyncManager: Pull failed {resp_dict['status']}")
                      if resp_dict['status'] in (502, 503, 504):
                           self._set_reachable(False)
                      return
                 
                 self._set_reachable(True)
                 data = resp_dict['data']
                 if hasattr(data, "to_py"): data = data.to_py()
                 
            else:
                from js import fetch
                
                pull_options = {
                    "method": "GET",
                    "credentials": "include"
                }
                resp = await fetch(url, _to_js_obj(pull_options))
                
                if not resp.ok:
                    console.warn(f"SyncManager: Pull failed {resp.status}")
                    # 404/500/403 might mean server issues, but reachable. 
                    # Network errors throw exception. 
                    # If 503, maybe unreachable. simpler to assume reachable if we got a response code.
                    if resp.status in (502, 503, 504): # Gateway errors
                        self._set_reachable(False)
                    return
                
                self._set_reachable(True) # Success confirms reachability

                data = await resp.json()
                if hasattr(data, "to_py"): data = data.to_py()
            
            documents = data.get("documents", [])
            checkpoint = data.get("checkpoint")
            
            console.log(f"SyncManager: Pull received {len(documents)} docs")

            if not documents:
                return

            # Apply changes with conflict detection
            # We assume documents have { table, key, value, deleted: bool, _rev: str }
            # We use silent=True to avoid triggering hooks (echo prevention)
            
            # Pre-fetch pending mutations to identify "Dirty" records
            queue_items = await self.queue.peek(9999)
            # Add null check for i
            pending_keys = set((i.get("table"), i.get("value", {}).get("ref_row")) for i in queue_items if i)
            
            conflicts_resolved = 0
            
            # Process documents from server
            for d in documents:
                table_name = d["table"]
                key = d["key"]
                
                # Get value first!
                val = d.get("value")

                # Safely handle JsNull or None
                if val is None:
                    val = {}
                elif hasattr(val, "to_py"):
                    val = val.to_py() # Ensure we have a python dict if possible
                elif str(val) == "[object PyProxy]":
                     # Fallback if to_py missing but still proxy (JsNull shouldn't be here if converted)
                     pass

                # If checking if val is effectively empty/null for logic
                if not val and not isinstance(val, dict):
                     val = {}

                val_wrapper = d # Keep reference to wrapper for metadata extraction
                _deleted = d.get("_deleted", False) or d.get("deleted", False)
                
                # Safe access to _rev
                val_rev = val.get("_rev") if isinstance(val, dict) else None
                remote_rev = d.get("_rev") or val_rev
                
                # If deleted, treat val as tombstone or create one if val is None
                if _deleted:
                     # For deleted items, val is often None. Initialize as tombstone dict.
                     if not isinstance(val, dict): val = {}
                     val["_deleted"] = True
                     
                table = self.db.table(table_name)
                if not table: continue
                
                is_dirty = (table_name, key) in pending_keys
                
                if _deleted:
                    # Create Tombstone for remote_doc to allow LWW comparison
                    # Try to get _lastModified from top-level doc or default to 0
                    tombstone = {
                        "_rev": remote_rev or "deleted",
                        "_lastModified": d.get("_lastModified", 0),
                        "_deleted": True
                    }

                    
                    # Key Correction:
                    # User states that key in payload might be different from record ID.
                    # We must prioritize table.primary_key from val if available.
                    target_key = key
                    if table.primary_key and val and isinstance(val, dict):
                         pk_val = val.get(table.primary_key)
                         if pk_val: target_key = pk_val
                    
                    # If local is dirty, it's a conflict. If clean, safe to delete.
                    if is_dirty:
                        local_doc = await table.get(target_key)
                        conflict = Conflict(
                            table_name=table_name,
                            key=target_key,
                            local_doc=local_doc,
                            remote_doc=tombstone, 
                            local_rev=_get_revision(local_doc) if local_doc else None,
                            remote_rev=remote_rev or "deleted"
                        )
                        resolved = await self._resolve_conflict(conflict, table, target_key)
                        if resolved:
                            conflicts_resolved += 1
                    else:
                        # Fast-Forward Delete
                        # Use update() to merge tombstone/deleted flag into existing record.
                        # This preserves local data while marking as deleted.
                        tombstone_req = val if val else {"_deleted": True}
                        if not tombstone_req.get("_id"): tombstone_req["_id"] = target_key
                        # Ensure we keep the revision if it was in the top-level doc wrapper or val
                        if "_rev" in val_wrapper: tombstone_req["_rev"] = val_wrapper["_rev"]
                        if "_deleted" not in tombstone_req: tombstone_req["_deleted"] = True

                        await table.update(target_key, tombstone_req, silent=True)
                else:
                    # Ensure remote document has revision
                    if val and isinstance(val, dict):
                        if not remote_rev:
                            remote_rev = _set_revision(val)
                        else:
                            val["_rev"] = remote_rev
                    
                    if is_dirty:
                        # Conflict!
                        local_doc = await table.get(key)
                        local_rev = _get_revision(local_doc) if local_doc else None
                        
                        conflict = Conflict(
                            table_name=table_name,
                            key=key,
                            local_doc=local_doc,
                            remote_doc=val,
                            local_rev=local_rev,
                            remote_rev=remote_rev
                        )
                        resolved = await self._resolve_conflict(conflict, table, key)
                        if resolved:
                            conflicts_resolved += 1
                    else:
                        # Fast-Forward Update
                        try:
                            await table.put(val, key=key, silent=True)
                        except Exception as e:
                            # Handle Unique Constraint Violation (ConstraintError)
                            err_msg = str(e)
                            if "ConstraintError" in err_msg:
                                console.warn(f"SyncManager: ConstraintError for {table_name}:{key}. Attempting to resolve via Conflict Strategy.")
                                
                                # Strategy: Resolve conflict by checking Strategy (Server Wins, Local Wins, etc)
                                
                                # 1. Try to parse index name from error message to find conflicting local record
                                import re
                                match = re.search(r"index ['\"](.*?)['\"]", err_msg, re.IGNORECASE)
                                
                                conflicting_keys = []
                                
                                if match:
                                    index_name = match.group(1)
                                    # We need to know the keyPath (column) for this index to look it up in 'val'
                                    # Optimistic assumption: index_name is the column name (common in metafor)
                                    if val and index_name in val:
                                        col_val = val[index_name]
                                        rec = await table.where(index_name).equals(col_val).include_deleted().first()
                                        if rec:
                                            c_key = rec.get(table.primary_key) if table.primary_key else (rec.get("id") or rec.get("uuid") or rec.get("_id"))
                                            if c_key and c_key != key:
                                                 conflicting_keys.append(c_key)
                                
                                if not conflicting_keys:
                                    # Fallback: Robustly scan ALL unique indexes
                                    # This is necessary because some browsers/implementations don't include index name in error
                                    try:
                                         unique_indexes = await self._get_unique_indexes(table_name)
                                         
                                         for idx_info in unique_indexes:
                                             idx_name = idx_info["name"]
                                             key_path = idx_info["keyPath"]
                                             
                                             # Support simple keyPath (string)
                                             if isinstance(key_path, str):
                                                 if key_path in val:
                                                     check_val = val[key_path]
                                                     # Check if a record exists with this unique value
                                                     rec = await table.where(idx_name).equals(check_val).include_deleted().first()
                                                     if rec:
                                                          c_key = rec.get(table.primary_key) if table.primary_key else (rec.get("id") or rec.get("uuid") or rec.get("_id"))
                                                          if c_key and c_key != key:
                                                               console.log(f"SyncManager: Detected conflict on unique index '{idx_name}' ({key_path}={check_val})")
                                                               conflicting_keys.append(c_key)
                                             # TODO: Support compound keys (list)
                                    except Exception as scan_e:
                                         console.warn(f"SyncManager: Failed to scan unique indexes: {scan_e}")

                                if conflicting_keys:
                                     # Resolve using Conflict Strategy
                                     for c_key in set(conflicting_keys):
                                          conflict_rec = await table.get(c_key, include_deleted=True)
                                          if not conflict_rec: continue 

                                          # Create Conflict Object
                                          conflict = Conflict(
                                              table_name=table_name,
                                              key=c_key, # Use local key as the conflict identifier
                                              local_doc=conflict_rec,
                                              remote_doc=val,
                                              local_rev=_get_revision(conflict_rec), # Helper must be available
                                              remote_rev=remote_rev
                                          )
                                          
                                          # Use system strategy to pick winner
                                          resolved_doc = await self._resolve_conflict(conflict, table, c_key, apply=False)
                                          
                                          if resolved_doc == val: # Remote Doc won (by object identity or content)
                                               console.log(f"SyncManager: Constraint Conflict Resolved (Remote Wins/LWW). Deleting local {c_key} to make way for {key}.")
                                               # Use put() for tombstone
                                               tombstone_c = {"_deleted": True, "_id": c_key}
                                               if table.primary_key: tombstone_c[table.primary_key] = c_key
                                               
                                               await table.put(tombstone_c, key=c_key, silent=True)
                                               
                                               try:
                                                    await table.put(val, key=key, silent=True)
                                                    console.log("SyncManager: Retry successful.")
                                               except Exception as retry_err:
                                                    console.error(f"SyncManager: Retry failed after cleanup: {retry_err}")
                                                    continue
                                          elif resolved_doc == conflict_rec: # Local Doc won
                                               console.log(f"SyncManager: Constraint Conflict Resolved (Local Wins). Keeping local {c_key}, ignoring remote {key}.")
                                               continue
                                          elif resolved_doc is None:
                                               console.warn(f"SyncManager: No resolution returned for {c_key}, skipping.")
                                               continue
                                          else:
                                               console.warn("SyncManager: Merge strategy for unique conflict not fully supported, ignoring remote.")
                                               continue

                                else:
                                     console.error(f"SyncManager: Could not identify conflicting record for {table_name}:{key}. Skipping document.")
                                     # Swallow error to keep loop alive
                                     continue
                            else:
                                # Not a constraint error, log and continue
                                console.error(f"SyncManager: Put failed for {table_name}:{key}: {e}")
                                continue
            
            if conflicts_resolved > 0:
                console.log(f"SyncManager: Resolved {conflicts_resolved} conflicts")
                    
            # Update Checkpoint
            if checkpoint:
                await self.state.set_cursor(checkpoint)
                
                
        except Exception as e:
            console.error(f"SyncManager Pull Error: {e}")
            # Likely network error
            self._set_reachable(False)

    async def _resolve_conflict(self, conflict: Conflict, table: Table, key: Any, apply: bool = True) -> Any:
        """
        Resolve a conflict using the configured strategy.
        If apply is True (default), writes the resolution to DB and returns boolean success.
        If apply is False, returns the resolved document (or None if no resolution).
        """
        try:
            # Record conflict for history
            await self.conflict_history.record(conflict)
            
            resolved_doc = None
            
            # ... (strategy logic omitted for brevity, logic remains same) ...
            if self.conflict_strategy == self.ConflictStrategy.LAST_WRITE_WINS:
                # Compare timestamps if available
                local_time = conflict.local_doc.get("_lastModified", 0) if conflict.local_doc else 0
                remote_time = conflict.remote_doc.get("_lastModified", 0) if conflict.remote_doc else 0
                
                if local_time > remote_time:
                    resolved_doc = conflict.local_doc
                    console.log(f"SyncManager: Conflict resolved (last-write-wins): local wins for {conflict.table_name}:{key}")
                else:
                    resolved_doc = conflict.remote_doc
                    console.log(f"SyncManager: Conflict resolved (last-write-wins): remote wins for {conflict.table_name}:{key}")
            
            elif self.conflict_strategy == self.ConflictStrategy.LOCAL_WINS:
                resolved_doc = conflict.local_doc
                console.log(f"SyncManager: Conflict resolved (local-wins): {conflict.table_name}:{key}")
            
            elif self.conflict_strategy == self.ConflictStrategy.REMOTE_WINS:
                resolved_doc = conflict.remote_doc
                console.log(f"SyncManager: Conflict resolved (remote-wins): {conflict.table_name}:{key}")
            
            elif self.conflict_strategy == self.ConflictStrategy.MERGE:
                # 3-Way Merge: Base, Local, Remote
                base_doc = None
                
                # Try to find base_doc in Offline Queue (it represents the state before local edits)
                queue_items = await self.queue.peek(9999) # Scan queue (optimize later)
                pending = next((i for i in queue_items if i and i.get("table") == conflict.table_name and i.get("value", {}).get("ref_row") == key), None)
                
                if pending and pending.get("base_doc"):
                    base_doc = pending.get("base_doc")
                    console.log(f"SyncManager: Found base_doc in queue for merge: rev={base_doc.get('_rev')}")
                
                if conflict.local_doc and conflict.remote_doc and base_doc:
                    # Perform 3-Way Merge
                    resolved_doc = {}
                    all_keys = set(conflict.local_doc.keys()) | set(conflict.remote_doc.keys()) | set(base_doc.keys())
                    
                    for k in all_keys:
                        if k.startswith("_"): continue # Skip metadata for logic, add back later
                        
                        base_val = base_doc.get(k)
                        local_val = conflict.local_doc.get(k)
                        remote_val = conflict.remote_doc.get(k)
                        
                        if local_val == remote_val:
                            resolved_doc[k] = local_val
                        elif local_val == base_val and remote_val != base_val:
                            # Remote changed it, Local didn't -> Take Remote
                            resolved_doc[k] = remote_val
                        elif remote_val == base_val and local_val != base_val:
                            # Local changed it, Remote didn't -> Take Local
                            resolved_doc[k] = local_val
                        else:
                            # Both changed it differently -> Conflict!
                            # For automatic merge, we often prefer Remote or Local. 
                            # Let's prefer Remote (server authority) for collision.
                            resolved_doc[k] = remote_val
                            
                    # Add back metadata from Remote (it usually wins for _rev, _lastModified)
                    resolved_doc["_rev"] = conflict.remote_doc.get("_rev")
                    resolved_doc["_lastModified"] = time.time() * 1000
                    
                    # Generate a NEW revision for the merged result? 
                    # Actually, if we merge, we are creating a NEW version on top of Remote.
                    # So we should rotate.
                    _set_revision(resolved_doc, parent_rev=resolved_doc["_rev"])
                    
                    console.log(f"SyncManager: 3-Way Merge successful for {conflict.table_name}:{key}")

                elif conflict.local_doc and conflict.remote_doc:
                     # Fallback to 2-way merge if no base (simple overlay)
                    resolved_doc = {**conflict.local_doc, **conflict.remote_doc}
                    resolved_doc["_lastModified"] = time.time() * 1000
                    _set_revision(resolved_doc, parent_rev=conflict.remote_doc.get("_rev"))
                    console.log(f"SyncManager: 2-Way Merge (No Base) for {conflict.table_name}:{key}")
                elif conflict.remote_doc:
                    resolved_doc = conflict.remote_doc
                else:
                    resolved_doc = conflict.local_doc
            
            elif self.conflict_strategy == self.ConflictStrategy.CUSTOM:
                if self.conflict_handler:
                    # Call custom handler
                    if asyncio.iscoroutinefunction(self.conflict_handler):
                        resolved_doc = await self.conflict_handler(conflict)
                    else:
                        resolved_doc = self.conflict_handler(conflict)
                    
                    if resolved_doc is None:
                        console.warn(f"SyncManager: Custom conflict handler returned None for {conflict.table_name}:{key}, keeping local")
                        resolved_doc = conflict.local_doc
                    else:
                        # Ensure resolved document has a revision
                        _set_revision(resolved_doc)
                        console.log(f"SyncManager: Conflict resolved (custom): {conflict.table_name}:{key}")
                else:
                    console.warn(f"SyncManager: Custom strategy but no handler provided, falling back to local-wins")
                    resolved_doc = conflict.local_doc
            else:
                # Unknown strategy, default to local-wins
                console.warn(f"SyncManager: Unknown conflict strategy '{self.conflict_strategy}', using local-wins")
                resolved_doc = conflict.local_doc
            
            if not apply:
                return resolved_doc

            # Apply resolved document
            if resolved_doc and resolved_doc.get("_deleted"):
                 # Resolved to delete
                 # Apply tombstone directly
                 await table.put(resolved_doc, key=key, silent=True)
                 return True
            elif resolved_doc:
                 # Normal update
                 await table.put(resolved_doc, key=key, silent=True)
                 return True
            else:
                 # Should not happen
                 return True

                
        except Exception as e:
            console.error(f"SyncManager: Error resolving conflict for {conflict.table_name}:{key}: {e}")
            # On error, default to keeping local document
            if conflict.local_doc:
                await table.put(conflict.local_doc, key=key, silent=True)
            return False

    async def _get_unique_indexes(self, table_name: str) -> List[Dict[str, Any]]:
        """
        Returns a list of unique indexes for the table.
        Format: [{'name': 'indexName', 'keyPath': 'column'}]
        """
        def get_indexes_logic(store):
            from js import Array
            unique_list = []
            names = store.indexNames
            # IDBDOMStringList is not iterable in all Pyodide versions directly, use length/item
            length = names.length
            for i in range(length):
                name = names.item(i)
                idx = store.index(name)
                if idx.unique:
                    # Capture safely
                    kp = idx.keyPath
                    # Normalize keyPath (it can be JS proxy)
                    if hasattr(kp, "to_py"): kp = kp.to_py()
                    
                    unique_list.append({"name": name, "keyPath": kp})
                    
            return _to_js_obj(unique_list)

        try:
            res = await self.db._execute_ro(table_name, get_indexes_logic)
            if hasattr(res, "to_py"): res = res.to_py()
            return res
        except Exception as e:
            console.warn(f"SyncManager: Failed to query index metadata: {e}")
            return []

    async def _push(self):
        try:
            mutations = await self.queue.peek(50)
            if not mutations: return

            # Transform for transport
            hydrated_mutations = []
            
            for m in mutations:
                if not m: continue
                val = m.get("value")
                record_id = None
                # Check for reference object structure (State-Based Sync)
                if m.get("op") in ("put", "update") and isinstance(val, dict) and "ref_row" in val:
                    record_id = val["ref_row"]

                if m.get("op") in ("put", "update") and record_id is not None:
                    # Hydrate from DB
                    table = self.db.table(m["table"])
                    if table:
                        current_val = await table.get(record_id, include_deleted=True)
                        if current_val:
                            # Ensure revision is present
                            if "_rev" not in current_val:
                                _set_revision(current_val)
                            m["value"] = current_val
                            hydrated_mutations.append(m)
                        else:
                            # Document deleted locally, skip push
                            console.log(f"SyncManager: Skipping push for {m['table']}:{record_id} - Document not found (deleted?)")
                            pass
                else:
                    hydrated_mutations.append(m)

            if not hydrated_mutations:
                 # If all were skipped, remove from queue and return
                 ids = [m["id"] for m in mutations if m]
                 await self.queue.remove(ids)
                 return

            # Check for Soft Deletes (Updates with _deleted=True)
            # Transform them to 'delete' op for server compatibility, BUT keep the value.
            for m in hydrated_mutations:
                if m.get("op") in ("update", "put"):
                    val = m.get("value")
                    # Use duck typing instead of strict isinstance(dict) because val might be a JsProxy
                    is_deleted = False
                    try:
                        if val and (val.get("_deleted") or val.get("deleted")):
                            is_deleted = True
                    except:
                        pass
                        
                    if is_deleted:
                        m["op"] = "delete"
                        # Ensure base_rev is present for delete
                        if "_rev" in val and "base_rev" not in m:
                            m["base_rev"] = val["_rev"]

            payload = {
                "mutations": hydrated_mutations,
                "client_id": str(self.db.name) # Use DB name or unique client ID
            }
            
            # Send to server (Using fetch or http_client)
            if self.http_client:
                 try:
                     resp_dict = await self.http_client.post(f"{self.upstream_url}{self.push_path}", data=payload)
                 except Exception as inner_e:
                     console.error(f"SyncManager: http_client.post failed: {inner_e!r}")
                     raise inner_e

                 if 200 <= resp_dict['status'] < 300:
                      data = resp_dict['data']
                      if hasattr(data, "to_py"): data = data.to_py()
                 else:
                      console.warn(f"SyncManager: Push failed {resp_dict['status']}")
                      if resp_dict['status'] in (502, 503, 504):
                           self._set_reachable(False)
                      return
            else:
                # implementation detail: assumed endpoint format
                from js import fetch, JSON, Object
                
                headers = {"Content-Type": "application/json"}
                
                # Create a Headers object
                js_headers = window.Headers.new()
                for k, v in headers.items():
                    js_headers.append(k, v)

                options = {
                    "method": "POST",
                    "headers": js_headers,
                    "body": JSON.stringify(_to_js_obj(payload)),
                    "credentials": "include"
                }
                
                resp = await fetch(f"{self.upstream_url}{self.push_path}", _to_js_obj(options))
                
                if resp.ok:
                    # Parse confirmation receipt
                    data = await resp.json()
                    if hasattr(data, "to_py"): data = data.to_py()
                else:
                    console.warn(f"SyncManager: Push failed {resp.status}")
                    if resp.status in (502, 503, 504):
                        self._set_reachable(False)
                    return
            
            receipts = data.get("sync_receipts", [])
            confirmed_keys = set()
            for r in receipts:
                if isinstance(r, dict) and "key" in r:
                    confirmed_keys.add(r["key"])

            # Remove processed items
            # 1. Skipped items (not in hydrated_mutations) are always removed (locally handled)
            # 2. Sent items are removed ONLY if confirmed by server
            sent_mutation_ids = set(m["id"] for m in hydrated_mutations)
            ids_to_remove = []
            
            for m in mutations:
                if m["id"] not in sent_mutation_ids:
                    ids_to_remove.append(m["id"])
                elif m["id"] in confirmed_keys:
                    ids_to_remove.append(m["id"])
            
            if ids_to_remove:
                await self.queue.remove(ids_to_remove)
                console.log(f"SyncManager: Pushed and confirmed {len(ids_to_remove)} mutations")
            
            self._set_reachable(True) # Success

        except Exception as e:
            console.error(f"SyncManager Push Error: {e}")
            self._set_reachable(False)
