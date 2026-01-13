from metafor.storage import Indexie
from metafor.form.schema import Schema
from api_client import http_client

# Initialize Indexie DB
db = Indexie("MyApp")

# Define Schema
db.version(2).stores({
    "myStore": "++id",
    "users": "++id, &email, name"
})

db.enable_sync(
    upstream_url="http://localhost:8000/sync", 
    pull_enabled=True,
    poll_timeout=30,
    debounce_interval=500,
    http_client=http_client
)

# Define User Schema Validation
user_schema = Schema()
user_schema.field("id").int().optional()
user_schema.field("name").string().required().trim()
user_schema.field("email").string().email().required().trim()
# You can add more fields here as needed, e.g.
# user_schema.field("role").string().optional()

# Attach schema to table
db.users.attach_schema(user_schema)
