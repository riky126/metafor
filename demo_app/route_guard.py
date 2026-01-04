from app_state import container, counter_provider, app_provider
from metafor.hooks import use_provider
from services import fetch_user

async def is_user_logged_in(from_route, to_route, **kwargs):
    # await asyncio.sleep(0)
    print("From route:", from_route.path)
    print("To route meta:", to_route.meta)
    
    if to_route.path != "/login" and not to_route.meta.get("requires_auth", False):
        print("From route doesn't requires auth")
        return False  # Block access
    
    app_state, set_state = use_provider(container, app_provider)

    if app_state()['auth_user']:
        return None  # Allow access
    
    auth_user = await fetch_user()
    
    if isinstance(auth_user, Exception):
        return "/login"  # Redirect on error
    
    set_state({"auth_user": auth_user})
    return None  # Allow access