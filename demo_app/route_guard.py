from app_state import container, counter_provider, app_provider
from metafor.hooks import use_provider
from services import fetch_user

async def is_user_logged_in(from_route, to_route, **kwargs):
    # await asyncio.sleep(0)
    print(f"From route: {to_route.meta}")
    print(f"To route: {to_route.path}")

    if not to_route.meta.get("requires_auth", False):
        print("From route requires auth")
        return False
    
    app_state, set_state = use_provider(container, app_provider)

    if app_state()['auth_user']:
        return True
    
    auth_user = await fetch_user()
    
    if isinstance(auth_user, Exception):
        return False
    
    set_state({"auth_user": auth_user})
    return True