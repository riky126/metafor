
import asyncio
import time
import uuid
import hashlib
import json
from typing import Any, Dict, List, Optional, Callable, Union
from js import console, navigator, window
from pyodide.ffi import create_proxy

from .plugin import Table, HookRegistrar
from .support import IndexedDBError, _to_js_obj


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

def _generate_revision(doc: Dict[str, Any]) -> str:
    """Generate a revision string for a document based on its content."""
    # Create a deterministic hash from document content
    # Exclude revision and metadata fields
    doc_copy = {k: v for k, v in doc.items() 
                if not k.startswith('_') or k == '_id'}
    doc_str = json.dumps(doc_copy, sort_keys=True)
    # Use a simple hash (in browser/Pyodide, we can use hashlib)
    try:
        hash_obj = hashlib.md5(doc_str.encode())
        return hash_obj.hexdigest()[:16]  # 16 char revision
    except Exception:
        # Fallback: use Python's built-in hash (works in Pyodide)
        # Convert to positive hex string
        hash_val = abs(hash(doc_str))
        return hex(hash_val)[2:18] if hash_val > 0 else hex(-hash_val)[2:18]


def _get_revision(doc: Dict[str, Any]) -> Optional[str]:
    """Get the revision from a document, or None if not present."""
    return doc.get("_rev")


def _set_revision(doc: Dict[str, Any], rev: Optional[str] = None) -> str:
    """Set or generate a revision for a document. Returns the revision."""
    if rev is None:
        rev = _generate_revision(doc)
    doc["_rev"] = rev
    doc["_lastModified"] = time.time() * 1000
    return rev


def _ensure_revision(doc: Dict[str, Any]) -> str:
    """Ensure a document has a revision. Returns the revision."""
    if "_rev" not in doc:
        return _set_revision(doc)
    return doc["_rev"]


class OfflineQueue:
    TABLE_NAME = "_sys_sync_queue"

    def __init__(self, db):
        self.db = db
        # We need to ensure the table exists. 
        # For now, we assume it's created via schema injection in Indexie.
        self.table = Table(self.TABLE_NAME, db, primary_key="id")

    async def enqueue(self, table_name: str, op: str, key: Any, value: Any = None):
        # Ensure value has a revision if it's a document
        if value and isinstance(value, dict) and op in ("put", "add"):
            _ensure_revision(value)
        
        mutation = {
            "id": str(uuid.uuid4()),
            "table": table_name,
            "op": op,
            "key": key,
            "value": value,
            "timestamp": time.time() * 1000
        }
        console.log(f"OfflineQueue: Attempting to add mutation: {mutation}")
        await self.table.add(mutation)
        console.log(f"OfflineQueue: Enqueued {op} for {table_name}:{key}")

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
                 conflict_strategy: str = ConflictStrategy.LAST_WRITE_WINS):
        self.db = db
        self.upstream_url = upstream_url
        self.push_interval = push_interval
        self.pull_enabled = pull_enabled
        self.conflict_handler = conflict_handler
        self.conflict_strategy = conflict_strategy
        
        self.queue = OfflineQueue(db)
        self.state = ReplicationState(db)
        self.conflict_history = ConflictHistory(db)
        
        self._is_online = navigator.onLine
        self._sync_task = None
        self._running = False

    @property
    def is_online(self) -> bool:
        return self._is_online

    def start(self):
        self._running = True
        
        # Monitor Online/Offline
        self._setup_network_listeners()
        
        # Start Hooks
        self._attach_hooks()
        
        # Start Loop
        self._sync_task = asyncio.create_task(self._process_loop())
        console.log("SyncManager: Started")

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
            
            # Capture closure variables
            table_name = name 
            
            # Add Hook
            async def on_add(payload):
                item = payload["item"].copy() if payload.get("item") else None
                # Ensure revision is set when enqueueing
                if item:
                    _ensure_revision(item)
                await self.queue.enqueue(table_name, "put", payload["key"], item)
            
            async def on_update(payload):
                item = payload["item"].copy() if payload.get("item") else None
                # Ensure revision is set when enqueueing
                if item:
                    _ensure_revision(item)
                await self.queue.enqueue(table_name, "put", payload["key"], item)
                
            async def on_delete(payload):
                await self.queue.enqueue(table_name, "delete", payload["key"])

            table.hook.on_add(on_add)
            table.hook.on_update(on_update)
            table.hook.on_delete(on_delete)
            
            console.log(f"SyncManager: Attached hooks to {table_name}")

    async def _process_loop(self):
        while self._running:
            if self._is_online:
                await self._push()
                if self.pull_enabled:
                    await self._pull()
            
            await asyncio.sleep(self.push_interval / 1000)

    async def _pull(self):
        try:
            cursor = await self.state.get_cursor()
            
            # Construct URL
            url = f"{self.upstream_url}/pull"
            if cursor:
                url += f"?checkpoint={cursor}"
                
            from js import fetch
            
            pull_options = {
                "method": "GET",
                "credentials": "include"
            }
            resp = await fetch(url, _to_js_obj(pull_options))
            
            if not resp.ok:
                console.warn(f"SyncManager: Pull failed {resp.status}")
                return

            data = await resp.json()
            if hasattr(data, "to_py"): data = data.to_py()
            
            documents = data.get("documents", [])
            checkpoint = data.get("checkpoint")
            
            if not documents:
                return

            console.log(f"SyncManager: Pull received {len(documents)} docs")

            # Apply changes with conflict detection
            # We assume documents have { table, key, value, deleted: bool, _rev: str }
            # We use silent=True to avoid triggering hooks (echo prevention)
            
            conflicts_resolved = 0
            
            for doc in documents:
                table_name = doc.get("table")
                key = doc.get("key")
                val = doc.get("value")
                deleted = doc.get("deleted", False)
                remote_rev = doc.get("_rev")
                
                table = self.db.table(table_name)
                if not table: continue
                
                if deleted:
                    # For deletes, check if local document exists and has been modified
                    local_doc = await table.get(key)
                    if local_doc and _get_revision(local_doc):
                        # Conflict: local document exists but remote says delete
                        conflict = Conflict(
                            table_name=table_name,
                            key=key,
                            local_doc=local_doc,
                            remote_doc=None,  # Deleted
                            local_rev=_get_revision(local_doc),
                            remote_rev=remote_rev or "deleted"
                        )
                        resolved = await self._resolve_conflict(conflict, table, key)
                        if resolved:
                            conflicts_resolved += 1
                    else:
                        # No conflict, safe to delete
                        await table.delete(key, silent=True)
                else:
                    # Ensure remote document has revision
                    if val and isinstance(val, dict):
                        if not remote_rev:
                            remote_rev = _set_revision(val)
                        else:
                            val["_rev"] = remote_rev
                    
                    # Check for conflicts with local document
                    local_doc = await table.get(key)
                    
                    if local_doc:
                        local_rev = _get_revision(local_doc)
                        if local_rev and local_rev != remote_rev:
                            # Conflict detected!
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
                            # No conflict, safe to update
                            await table.put(val, key=key, silent=True)
                    else:
                        # New document, no conflict
                        await table.put(val, key=key, silent=True)
            
            if conflicts_resolved > 0:
                console.log(f"SyncManager: Resolved {conflicts_resolved} conflicts")
                    
            # Update Checkpoint
            if checkpoint:
                await self.state.set_cursor(checkpoint)
                
        except Exception as e:
            console.error(f"SyncManager Pull Error: {e}")

    async def _resolve_conflict(self, conflict: Conflict, table: Table, key: Any) -> bool:
        """
        Resolve a conflict using the configured strategy.
        Returns True if conflict was resolved, False otherwise.
        """
        try:
            # Record conflict for history
            await self.conflict_history.record(conflict)
            
            resolved_doc = None
            
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
                # Simple merge: combine fields, remote takes precedence for overlapping keys
                if conflict.local_doc and conflict.remote_doc:
                    resolved_doc = {**conflict.local_doc, **conflict.remote_doc}
                    # Preserve local _rev but update timestamp
                    resolved_doc["_lastModified"] = time.time() * 1000
                    _set_revision(resolved_doc)  # Generate new revision
                    console.log(f"SyncManager: Conflict resolved (merge): {conflict.table_name}:{key}")
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
            
            # Apply resolved document
            if resolved_doc is None:
                # Remote was deleted, but we're keeping local
                return True  # Conflict handled (kept local)
            elif conflict.remote_doc is None:
                # Remote delete, but we resolved to keep local
                # Don't delete, just update revision
                _set_revision(resolved_doc)
                await table.put(resolved_doc, key=key, silent=True)
                return True
            else:
                # Normal update
                await table.put(resolved_doc, key=key, silent=True)
                return True
                
        except Exception as e:
            console.error(f"SyncManager: Error resolving conflict for {conflict.table_name}:{key}: {e}")
            # On error, default to keeping local document
            if conflict.local_doc:
                await table.put(conflict.local_doc, key=key, silent=True)
            return False

    async def _push(self):
        try:
            mutations = await self.queue.peek(50)
            if not mutations: return

            # Transform for transport
            payload = {
                "mutations": mutations,
                "client_id": str(self.db.name) # Use DB name or unique client ID
            }
            
            # Send to server (Using fetch)
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
            
            resp = await fetch(f"{self.upstream_url}/push", _to_js_obj(options))
            
            if resp.ok:
                # Remove processed
                ids = [m["id"] for m in mutations]
                await self.queue.remove(ids)
                console.log(f"SyncManager: Pushed {len(ids)} mutations")
            else:
                console.warn(f"SyncManager: Push failed {resp.status}")

        except Exception as e:
            console.error(f"SyncManager Push Error: {e}")
