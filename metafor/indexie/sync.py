
import asyncio
import time
import uuid
from typing import Any, Dict, List, Optional, Callable, Union
from js import console, navigator, window
from pyodide.ffi import create_proxy

from .plugin import Table, HookRegistrar
from .support import IndexedDBError

class OfflineQueue:
    TABLE_NAME = "_sys_sync_queue"

    def __init__(self, db):
        self.db = db
        # We need to ensure the table exists. 
        # For now, we assume it's created via schema injection in Indexie.
        self.table = Table(self.TABLE_NAME, db, primary_key="id")

    async def enqueue(self, table_name: str, op: str, key: Any, value: Any = None):
        mutation = {
            "id": str(uuid.uuid4()),
            "table": table_name,
            "op": op,
            "key": key,
            "value": value,
            "timestamp": time.time() * 1000
        }
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
    def __init__(self, db, upstream_url: str, push_interval: int = 5000, pull_enabled: bool = True):
        self.db = db
        self.upstream_url = upstream_url
        self.push_interval = push_interval
        self.pull_enabled = pull_enabled
        
        self.queue = OfflineQueue(db)
        self.state = ReplicationState(db)
        
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
        sys_tables = [OfflineQueue.TABLE_NAME, ReplicationState.TABLE_NAME]

        for name, table in self.db._tables.items():
            if name in sys_tables: continue
            
            # Capture closure variables
            table_name = name 
            
            # Add Hook
            async def on_add(payload):
                await self.queue.enqueue(table_name, "put", payload["key"], payload["item"])
            
            async def on_update(payload):
                await self.queue.enqueue(table_name, "put", payload["key"], payload["item"])
                
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
            resp = await fetch(url)
            
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

            # Apply changes
            # We assume documents have { table, key, value, deleted: bool }
            # We use silent=True to avoid triggering hooks (echo prevention)
            
            # Transactions? Ideally yes.
            
            for doc in documents:
                table_name = doc.get("table")
                key = doc.get("key")
                val = doc.get("value")
                deleted = doc.get("deleted", False)
                
                table = self.db.table(table_name)
                if not table: continue
                
                if deleted:
                    await table.delete(key, silent=True)
                else:
                    await table.put(val, key=key, silent=True)
                    
            # Update Checkpoint
            if checkpoint:
                await self.state.set_cursor(checkpoint)
                
        except Exception as e:
            console.error(f"SyncManager Pull Error: {e}")


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
            from js import fetch, JSON
            
            headers = {"Content-Type": "application/json"}
            
            # Create a Headers object
            js_headers = window.Headers.new()
            for k, v in headers.items():
                js_headers.append(k, v)

            options = {
                "method": "POST",
                "headers": js_headers,
                "body": JSON.stringify(to_js_obj(payload))
            }
            
            resp = await fetch(f"{self.upstream_url}/push", to_js_obj(options))
            
            if resp.ok:
                # Remove processed
                ids = [m["id"] for m in mutations]
                await self.queue.remove(ids)
                console.log(f"SyncManager: Pushed {len(ids)} mutations")
            else:
                console.warn(f"SyncManager: Push failed {resp.status}")

        except Exception as e:
            console.error(f"SyncManager Push Error: {e}")


def to_js_obj(py_obj):
    from pyodide.ffi import to_js
    return to_js(py_obj, dict_converter=to_js)
