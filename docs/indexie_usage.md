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

Use `.toArray()` to get all records in a table.

```python
all_users = await db.users.toArray()
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
*   **.startsWith(value)**: String prefix match.

### Executing Queries

After defining a where clause, execute it with:
*   **.toArray()**: Returns a list of matching records.
*   **.first()**: Returns the first matching record or `None`.
*   **.count()**: Returns the number of matching records.

### Examples

```python
# Find user by email
user = await db.users.where("email").equals("alice@example.com").first()

# Find all users named "Alice"
alices = await db.users.where("name").equals("Alice").toArray()

# Find users with age above 18
adults = await db.users.where("age").above(18).toArray()

# Find users whose name starts with "A"
a_names = await db.users.where("name").startsWith("A").toArray()
```

## Error Handling

Database operations can raise `IndexedDBError` or other exceptions. Always wrap DB calls in try/except blocks.

```python
try:
    await db.users.add({...})
except Exception as e:
    console.error("Database error:", str(e))
```
