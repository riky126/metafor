from metafor.storage import Indexie
from metafor.form.schema import Schema
import asyncio
from js import console

async def setup_sync_db():
    # 1. Initialize Indexie DB
    db = Indexie("MyAppSyncDemo")

    # 2. Define Schema
    # NOTE: If you are upgrading an existing DB, you MUST increment the version 
    # (e.g. from version(1) to version(2)) to trigger schema creation for sync tables.
    db.version(1).stores({
        "todos": "++id, title, done",
    })

    # 3. Enable Sync
    # The URL should point to your backend sync endpoints.
    # It expects:
    # - POST /push: Receives {"mutations": [...]}
    # - GET /pull?checkpoint=...: Returns {"documents": [...], "checkpoint": "..."}
    # This automatically registers the system tables (_sys_sync_queue, _sys_sync_state).
    #
    # IF USING ELECTRICSQL:
    # If you are using ElectricSQL for live updates, you should disable the built-in pull 
    # mechanism to avoid conflicts. The SyncManager will still handle offline queueing and pushing.
    # db.enable_sync("http://localhost:8000/api/sync", pull_enabled=False)
    #
    db.enable_sync("http://localhost:8000/api/sync")

    # 4. Open Database
    # This will initialize the SyncManager and start the background push/pull loop.
    await db.open()
    
    console.log("Database opened with Sync enabled!")

    # 5. Usage Example
    # Operations are identical to standard usage.
    # The SyncManager transparently hooks into these methods.
    
    # Enable offline simulation in browser to test queueing!
    await db.todos.add({"title": "Buy Milk", "done": False})
    
    # You can inspect the queue manually if needed:
    queue_count = await db.sync_manager.queue.count()
    console.log(f"Offline Queue Size: {queue_count}")
    
    # 6. Force manual actions (Optional)
    # db.sync_manager.stop()
    # await db.sync_manager._push()

# To run this in your Metafor app:
# asyncio.create_task(setup_sync_db())
