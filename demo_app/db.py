from metafor.storage import Indexie
from metafor.form.schema import Schema

# Initialize Indexie DB
db = Indexie("MyApp")

# Define Schema
db.version(2).stores({
    "myStore": "++id",
    "users": "++id, &email, name"
})

db.enable_sync("http://localhost:8000/sync", pull_enabled=True)

# Define User Schema Validation
user_schema = Schema()
user_schema.field("id").int().optional()
user_schema.field("name").string().required().trim()
user_schema.field("email").string().email().required().trim()
# You can add more fields here as needed, e.g.
# user_schema.field("role").string().optional()

# Attach schema to table
db.users.attach_schema(user_schema)
