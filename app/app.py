import asyncio
from js import console, Object
from pyodide.ffi import to_js

from metafor.core import create_signal, on_mount
from metafor.decorators import component
from metafor.hooks import use_context, use_provider
from metafor.dom import t
from metafor.context import ContextProvider
from metafor.dom import load_css
from metafor.storage import index_db

from contexts import ThemeContext, DBContext
from app_state import container, counter_provider, app_provider
from services import fetch_user
from routes import router

async def is_user_logged_in(from_route, to_route, **kwargs):
    # await asyncio.sleep(0)
    app_state, set_state = use_provider(container, app_provider)

    if app_state()['auth_user']:
        return True
    
    auth_user = await fetch_user()
    
    if isinstance(auth_user, Exception):
        return False
    
    set_state({"auth_user": auth_user})
    return True
    
@component()
def MyApp(children, **props):
    app_styles = load_css(css_path="app.css")
    
    count_value, _ = use_provider(container, counter_provider)
    
    router.add_guard("/", is_user_logged_in, "/login")
    
    theme = use_context(ThemeContext)

    db_api = None
    
    def setup_schema(session):
        console.log("Running schema setup for version:", session.DB.version)
        try:
            # Log and delete existing stores
            console.log("Existing stores before setup:", list(session.DB.objectStoreNames))

            # Create stores with explicit configuration
            options = {"keyPath": "id", "autoIncrement": True}
            my_store_index, my_store = db_api.create_store("myStore", options)
            
            user_store, _ = db_api.create_store("users", options)
            user_store("name", options={"unique": False})
            user_store("email", options={"unique": True})
            
            console.log("Schema setup completed successfully")
        except Exception as e:
            console.error("Schema setup error:", str(e))

    async def on_connect(DB):
        DBContext.set_value(DB)
        try:            
            # Check if user exists first to avoid ConstraintError logs
            existing_user = await DB.get_by_index("users", "email", "halem@mail.com")
            
            if not existing_user:
                user = await DB.create("users", {"name": "Nehalem Doe", "email": "halem@mail.com"})
                print("Created user:", user)
            else:
                console.log("User 'halem@mail.com' already exists.")
            
        except Exception as e:
            console.error("Connection error:", str(e))
    
    # Use a higher version to force schema update
    db_api = index_db("MyApp", on_connected=on_connect, on_upgrade=setup_schema, version=1)  # Increased version
    
    return t.div({
        "class_name": lambda: f"app theme-{theme()}"
    }, [
        # Router outlet content
        router.route_outlet(),
        # End outlet
        
        t.div({"id": "modal-root"}, [])

    ], css={"global": app_styles})

App = ContextProvider(ThemeContext, "light", MyApp)
