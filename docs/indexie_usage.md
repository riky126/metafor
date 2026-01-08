# Storage (Indexie)

Metafor provides a built-in, fluent API for interacting with IndexedDB called **Indexie**. It is heavily inspired by Dexie.js, offering a simple way to define schemas and perform database operations using async/await.

## Initialization

To use Indexie, import it from `metafor.storage` and create an instance with your database name.

```python
from metafor.storage import Indexie

db = Indexie("MyAppDatabase")
```

## Schema Definition

Define your database schema using `.version(n).stores(...)`. You can define multiple versions to handle migrations automatically.

The schema syntax is a string of comma-separated keys:
*   `++` prefix: Auto-incrementing primary key (e.g., `++id`).
*   `&` prefix: Unique index (e.g., `&email`).
*   No prefix: Standard index (e.g., `name`).

```python
# Define schema for version 1
db.version(1).stores({
    "users": "++id, &email, name, age",
    "todos": "++id, title, done"
})

# Add an upgrade hook for data migration
def on_upgrade_v2(txn):
    # Example: Dropping an old table during upgrade
    # Note: drop() is only valid in upgrade hooks
    db.oldStore.drop()

db.version(2).stores({
    "users": "++id, &email, name"
}).upgrade(on_upgrade_v2)
```

## Opening the Database

Before performing operations, you should open the database. This is async.

await db.open()
```

### Async Initialization

Since database operations are asynchronous, efficient usage typically involves scheduling them. Do **not** use `create_effect` directly with async functions, as it does not await coroutines. Instead, use `on_mount` combined with `asyncio.create_task`.

```python
import asyncio
from metafor.core import on_mount

async def init_db():
    await db.open()
    # ... other async db operations

def on_db_mount():
    asyncio.create_task(init_db())

on_mount(on_db_mount)
```

## Operations

Indexie provides a `Table` object for each store defined in your schema, accessible as attributes on the `db` instance (e.g., `db.users`).

### Adding Data

Use `.add()` to insert a new record. If an auto-increment key is used, it will be generated.

```python
user_id = await db.users.add({
    "name": "Alice",
    "email": "alice@example.com",
    "age": 30
})
```

Use `.put()` to insert or update a record (upsert).

```python
await db.users.put({
    "id": 1,
    "name": "Alice Updated"
})
```

### Retrieving Data

Use `.get(key)` to retrieve a single record by its primary key.

```python
user = await db.users.get(1)
```

Use `.to_array()` to get all records in a table.

```python
all_users = await db.users.to_array()
```

### Deleting Data

Use `.delete(key)` to remove a record by primary key.

```python
await db.users.delete(1)
```

Use `.clear()` to delete all records in a table.

```python
await db.users.clear()
```

## Querying

Indexie supports fluent querying using `.where(index)`.

### Supported Clauses

*   **.equals(value)**: Exact match.
*   **.above(value)**: Values greater than `value`.
*   **.below(value)**: Values less than `value`.
*   **.starts_with(value)**: String prefix match.
*   **.or_(index)**: Chain logical OR conditions (e.g. `.where("a").equals(1).or_("b").equals(2)`).

### Executing Queries

After defining a where clause, execute it with:
*   **.to_array()**: Returns a list of matching records.
*   **.first()**: Returns the first matching record or `None`.
*   **.count()**: Returns the number of matching records.

### Examples

```python
# Find user by email
user = await db.users.where("email").equals("alice@example.com").first()

# Find all users named "Alice"
alices = await db.users.where("name").equals("Alice").to_array()

# Find users with age above 18
adults = await db.users.where("age").above(18).to_array()

# Find users whose name starts with "A"
a_names = await db.users.where("name").starts_with("A").to_array()

# Pagination: get 2nd page of 10 users, sorted by name, reversed
page_2 = await db.users.order_by("name").reverse().offset(10).limit(10).to_array()

# OR query: Find users named "Alice" OR with age > 20
mixed = await db.users.where("name").equals("Alice").or_("age").above(20).to_array()
```

## Transactions

Execute multiple operations atomically using `db.transaction`.

```python
async def transfer_data():
    # Both operations succeed or fail together
    await db.users.add({"name": "New User"})
    await db.logs.add({"action": "User Created"})

# Run in readwrite transaction for "users" and "logs" tables
await db.transaction(Indexie.Mode.READ_WRITE, ["users", "logs"], transfer_data)
```

## Partial Updates

Update specific fields of an object without overwriting the whole record.

```python
# Updates only the age, preserving other fields
await db.users.update(1, {"age": 31})

## Error Handling

Database operations can raise `IndexedDBError` or other exceptions. Always wrap DB calls in try/except blocks.

```python
try:
    await db.users.add({...})
except Exception as e:
    console.error("Database error:", str(e))
```

### New Features
*   **.limit(n)**: Limit results.
*   **.offset(n)**: Skip first n results.
*   **.reverse()**: Reverse result order.
*   **.order_by(key)**: Sort results.
*   **.each(callback)**: Iterate over results.

## Reactive & Real-Time Sync

Indexie includes advanced features for building reactive, local-first applications.

### 1. Live Queries (`use_live_query`)

The `use_live_query` hook makes your UI automatically reactive to database changes. It tracks dependencies and re-runs the query whenever the underlying table data changes.

```python
from metafor.storage import use_live_query

# This list updates automatically when 'users' table changes
users = use_live_query(lambda: db.users.to_array())
```

### 2. Mutation Hooks & Optimistic Updates

You can register hooks to react to local changes. This is commonly used for **Optimistic UI** patterns, where you update the local DB immediately and sync to the backend in the background.

```python
# Async hooks are supported and awaited
async def on_user_add(payload):
    item = payload['item']
    # Sync item to your backend API
    await fetch("/api/users", method="POST", body=item)

# Register hook
db.users.hook.on_add(on_user_add)
# Also available: .on_update, .on_delete
```

#### Functional Updates
For "draft-style" updates (modifying current state), use a callable with `.update()`:

```python
# Updates age based on current value
await db.users.update(key, lambda user: user.update({"age": user["age"] + 1}))
```

### 3. ElectricSQL Sync

Indexie supports real-time synchronization with [ElectricSQL](https://electric-sql.com). It uses a hybrid approach:
1.  **Initial Snapshot**: Fetches current state via HTTP GET.
2.  **Live Stream**: Connects via Server-Sent Events (SSE) for real-time updates.

#### Basic Usage

```python
# Initialize Sync (usually in your init_db function)
await db.users.sync_electric(
    url="https://api.electric-sql.cloud/v1/shape",
    params={"table": "users"} # ElectricSQL Shape params
)
```

#### Authentication & Custom Headers

You can pass authentication headers or use a configured `metafor.http` client.

**Option 1: Passing Headers**

```python
await db.users.sync_electric(
    url="...",
    params={"table": "users"},
    headers={"Authorization": "Bearer YOUR_TOKEN"}
)
```

**Option 2: Using HTTP Client (for Interceptors)**

Use this to leverage your existing app client (and its interceptors) for the initial fetch.

```python
from metafor.http import Http

# Assuming your client has auth interceptors set up
await db.users.sync_electric(
    url="...",
    params={"table": "users"},
    http_client=db.http # Instance of metafor.http.client.Http
)
```

Incoming sync changes are applied "silently" to the local DB (updating the UI but *not* triggering your `on_add` hooks again), preventing sync loops.

### 4. Sync Strategies (`Strategy`)

Control when your local changes are applied relative to network requests.

```python
from metafor.storage import Strategy

# Configure per table
db.users.strategy = Strategy.LOCAL_FIRST # Default
```

*   **`Strategy.LOCAL_FIRST` (Optimistic)**:
    1.  Update Local DB immediately.
    2.  Update UI.
    3.  Trigger Hooks (e.g., `on_add`) to sync to network in background.
*   **`Strategy.LOCAL_FIRST` (Optimistic)**:
    1.  Update Local DB immediately.
    2.  Update UI.
    3.  Trigger Hooks (e.g., `on_add`) to sync to network in background.
    *   *Best for: Fast, responsive UIs.*

### 5. Transactions (Atomic & Optimistic)

Indexie provides a unified API for both **Optimistic** and **Standard (ACID)** transactions.

**Usage:** `async with table.start_transaction(optimistic=True|False) as tx:`

#### A. Optimistic Transactions (`optimistic=True`)

Best for "Offline First" or responsive UIs. Writes are immediately visible in `live_query` but not persisted until commit.

```python
# 1. Register Sync Hook (Implicit Sync Logic)
async def sync_to_server(payload):
    await api.post("/users", payload['item']) # Raise exception on failure

db.users.hook.on_add(sync_to_server)

# 2. UI Code
async def add_user():
    # Start Optimistic Transaction (Visible to UI)
    async with db.users.start_transaction(optimistic=True) as tx:
         
         # UI updates immediately here!
         await db.users.add(user_data) 

         # Commit: Attempts to persist to IndexedDB
         # Hooks run here. If hook fails, UI rolls back automatically.
         await tx.commit() 
```

#### B. Standard Transactions (`optimistic=False`)

Best for complex logic where you want "All-or-Nothing" UI updates. Writes are buffered invisibly.

```python
async def transfer_money():
    # Start Standard Transaction (Invisible to UI)
    async with db.users.start_transaction(optimistic=False) as tx:
         
         # Updates are buffered in memory
         await db.users.update(sender_id, {"balance": sender_bal - 100})
         await db.users.update(receiver_id, {"balance": receiver_bal + 100})

         try:
             # Atomic Commit: UI updates for both changes at once
             await tx.commit() 
         except Exception:
             # Rollback: Discard buffer (UI never flickered)
             await tx.rollback()
```
```

### 7. Sync Strategies
*   **`Strategy.NETWORK_FIRST` (Pessimistic)**:
    1.  Trigger Hooks first.
    2.  Wait for Hook to succeed (await).
    3.  Update Local DB.

### 6. Architecture Diagram

Indexie follows a **Local-First** architecture with an optional **Memory Overlay**.

```mermaid
graph TD
    UI[React/PTML UI]
    subgraph IndexieDB
        LQ[Live Queries]
        T[Table API]
        S[Signals]
        OL[Memory Overlay]
    end
    
    subgraph Storage
        IDB[(IndexedDB)]
    end
    
    subgraph Network
        API[Backend API]
    end

    %% Reads
    IDB -->|Data Stream| T
    OL -.->|Merged (If Visible)| T
    T -->|Updates Signal| S
    S -->|Re-runs| LQ
    LQ -->|Renders| UI

    %% Writes (Overlay Mode)
    UI -->|Mutation| T
    
    subgraph Transaction Context
        T -.->|Start Tx| OL
        T -->|Write| OL
        OL -->|Commit| IDB
        OL -.->|Rollback| Discard[Discard Changes]
    end

    T -->|Trigger Hook| API
```

*   **Reads**: `use_live_query` merges data from the **Memory Overlay** (if visible) and **IndexedDB**.
*   **Writes**: Mutations update the **Overlay**.
    *   **Optimistic (`optimistic=True`)**: Overlay is `visible`. UI updates instantly.
    *   **Standard (`optimistic=False`)**: Overlay is `hidden`. UI updates only on `commit`.
