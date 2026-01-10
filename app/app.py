from js import console, Object
from pyodide.ffi import to_js
import asyncio
from metafor.core import create_signal, create_effect, on_mount
from metafor.decorators import component
from metafor.hooks import use_context, use_provider
from metafor.dom import t
from metafor.context import ContextProvider
from metafor.dom import load_css
from metafor.indexie import Indexie

from contexts import ThemeContext, DBContext
from app_state import container, counter_provider, app_provider
from services import fetch_user
from routes import router

async def is_user_logged_in(from_route, to_route, **kwargs):
    # await asyncio.sleep(0)
    print("From route:", from_route.path if from_route else "None")
    print("To route meta:", to_route.meta)
    
    if not to_route.meta.get("requires_auth", False):
        print("From route requires auth")
        return True  # Allow access
    
    app_state, set_state = use_provider(container, app_provider)
    
    if app_state()['auth_user']:
        return None  # Allow access
    
    auth_user = await fetch_user()
    
    if isinstance(auth_user, Exception) or auth_user is None:
        return "/login"  # Redirect on error
    
    set_state({"auth_user": auth_user})
    return None  # Allow access
    
@component()
def MyApp(children, **props):
    app_styles = load_css(css_path="app.css")
    
    count_value, _ = use_provider(container, counter_provider)
    
    router.before_routing(is_user_logged_in)
    
    theme = use_context(ThemeContext)

    # Initialize Indexie DB
    db = Indexie("MyApp")
    
    # Define Schema
    db.version(1).stores({
        "myStore": "++id",
        "users": "++id, &email, name"
    })

    async def init_db():
        await db.open()
        DBContext.set_value(db)
        try:            
            # Check if user exists first to avoid ConstraintError logs
            existing_user = await db.users.where("email").equals("halem@mail.com").first()
            
            if not existing_user:
                user = await db.users.add({"name": "Nehalem Doe", "email": "halem@mail.com"})
                print("Created user:", user)
            else:
                console.log("User 'halem@mail.com' already exists.")
            
        except Exception as e:
            console.error("Connection error:", str(e))
    
    # Connect on mount
    def on_db_mount():
        asyncio.create_task(init_db())
        
    on_mount(on_db_mount)
    
    return t.div({
        "class_name": lambda: f"app theme-{theme()}"
    }, [
        # Router outlet content
        router.route_outlet(),
        # End outlet
        
        t.div({"id": "modal-root"}, [])

    ], css={"global": app_styles})

App = ContextProvider(ThemeContext, "light", MyApp)
