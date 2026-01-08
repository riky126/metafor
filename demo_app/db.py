from metafor.storage import Indexie

# Initialize Indexie DB
db = Indexie("MyApp")

# Define Schema
db.version(1).stores({
    "myStore": "++id",
    "users": "++id, &email, name"
})
