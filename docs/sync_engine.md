# Offline Sync Engine

The Metafor Sync Engine provides robust, offline-first data synchronization capabilities for `Indexie`, inspired by RxDB. It allows your application to function seamlessly without network connectivity, queuing changes locally and synchronizing them with a backend when connectivity is restored.

## Architecture

The Sync Engine sits between your application logic and the IndexedDB storage. It uses **Hooks** to intercept writes and an **Offline Queue** to store mutations.

```
┌───────────────────────────────────────────────────────────────┐
│                       APPLICATION LOGIC                       │
│  (Writes via db.table.add / db.table.put / db.table.delete)   │
└───────────────┬───────────────────────────────┬───────────────┘
                │                               │
                ▼                               ▼
    ┌───────────────────────┐       ┌───────────────────────┐
    │    Online (Default)   │       │   Offline / Direct    │
    │    (OverlayLayer)     │       │  (DirectTransaction)  │
    └──────┬─────────┬──────┘       └───────────┬───────────┘
           │         │                          │
           │         │ (Manual API Call)        │ (Direct Writes)
           │         ▼                          ▼
           │  ┌─────────────┐       ┌───────────────────────┐
           │  │ BACKEND API │       │      INDEXIE CORE     │
           │  └─────────────┘       └───────────┬───────────┘
           │                                    │
           │ (Optimistic Updates)               ▼
           ▼                        ┌───────────────────────┐
    ┌───────────────────────┐       │    HOOK SYSTEM        │
    │   In-Memory Overlay   │       │ (on_add, on_update)   │
    │   (UI Updates Fast)   │       └───────────┬───────────┘
    └───────────────────────┘                   │
                                                ▼
                                    ┌───────────────────────┐
                                    │     OFFLINE QUEUE     │
                                    │   (_sys_sync_queue)   │
                                    └───────────┬───────────┘
                                                │
                                                ▼
                                    ┌───────────────────────┐
                                    │     SYNC MANAGER      │
                                    │      (Background)     │
                                    │                       │
                                    │  ┌─────────────────┐  │
                                    │  │    PUSH LOOP    │  │
                                    │  │ (POST /push)    │──┼──► UPSTREAM
                                    │  └────────┬────────┘  │
                                    │           │           │
                                    │  ┌────────▼────────┐  │
                                    │  │    PULL LOOP    │◄─┼─── (Optional)
                                    │  │  (GET /pull)    │  │
                                    │  └─────────────────┘  │
                                    └───────────────────────┘
```

## features

### 1. Offline Queue
Any `add`, `put`, or `delete` operation performed on a table is transparently captured and stored in the `_sys_sync_queue` table. This happens regardless of network status (unless using Optimistic Transactions, see below).

### 2. Push/Pull Replication
-   **Push**: The `SyncManager` watches the queue and automatically sends batches of mutations to the configured upstream URL via `POST /push` when the devise is online.
-   **Pull**: By default, it periodically polls `GET /pull` to fetch downstream changes and applies them to the local database.

## Configuration

To enable sync, configure it before opening the database.

```python
db = Indexie("MyApp")

# Standard Configuration
db.enable_sync("https://api.example.com/sync")

await db.open()
```

### Integration with ElectricSQL / Replicache
If you are using a specialized sync solution like **ElectricSQL** for downstream updates (server-to-client), you should **disable** the built-in pull mechanism to avoid conflicts and redundant data fetching.

```python
# Disable Pull, keep Offline Queue + Push
db.enable_sync("https://api.example.com/sync", pull_enabled=False)
```

In this mode:
-   **Writes** are queued and pushed by `SyncManager`.
-   **Reads** are updated via your external stream (e.g., ElectricSQL SSE).

## Optimistic Transactions & Offline Support

The `start_transaction(optimistic=True)` context manager is network-aware, providing the best user experience based on connectivity.

### Online Behavior
-   **Mode**: Optimistic UI.
-   **Mechanism**: Writes are applied to an in-memory **Overlay**. The UI updates immediately.
-   **Sync**: These writes are **NOT** queued for sync. It is assumed that your code will make an API call to the backend immediately after the optimistic update.
-   **Outcome**: Instant feedback, no double-writes to queue.

### Offline Behavior
-   **Mode**: Direct Write / Queue.
-   **Mechanism**: Writes bypass the overlay and go **DIRECTLY** to IndexedDB.
-   **Sync**: These writes **TRIGGER** hooks and are added to the **Offline Queue**.
-   **Outcome**: Data is safely stored locally and will be synced automatically when the device goes back online.

### Usage Example

```python
async with db.todos.start_transaction(optimistic=True):
    # This single block handles both scenarios!
    await db.todos.add(new_todo)
    
    # If we are online, we should also tell the server
    if db.sync_manager.is_online:
         await api_client.create_todo(new_todo)
```
