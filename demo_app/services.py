from api_client import api, set_authorization_header
from metafor.http import HttpError
from metafor.storage import local_storage
from metafor.router import router_delegate
from app_state import container, app_provider
from metafor.hooks import use_provider

async def fetch_user():
    try:
        # User GET request
        response = await api.get("/user/")
        return response.get("data")
    except HttpError as e:
        return e
    
async def fetch_account():
    try:
        # Account GET request
        response = await api.get("/account/")
        return response.get("data")
    except HttpError as e:
        return e

async def do_auth(**credentials):
    """
    Authenticates a user with the provided email and password.
    Raises:
        HttpError: If the authentication request fails.
    """
    try:
        response = await api.post("/login/", credentials)

        # Check for successful authentication
        if response.get("status") == 200:
            data = response.get("data")
            set_authorization_header(data.accessToken)
        
            local_storage.save("access_tokens", {
                "access_token": data.accessToken,
                "refresh_token": data.refreshToken
            })
            return data
        
    except HttpError as e:
        return e
    
async def refresh_token():
  
    try:
        # Refresh Token request
        tokens = local_storage.load("access_tokens") or {}
        response = await api.post("/refresh/", {'refresh': tokens.get("refresh_token", '')})
        if response.get("status") == 200:
            return response.get("data")
        raise HttpError(response)        
    except HttpError as e:
        raise e

def do_logout():
    router = router_delegate()
    _, set_appstate = use_provider(container, app_provider)

    try:
        set_authorization_header("")
        local_storage.remove("access_tokens")
        set_appstate({"auth_user": None})

        router.go("/login")
    except Exception as e:
        print(f"Error logging out: {e}")

def is_authenticated():
    tokens = local_storage.load("access_tokens") or {}
    app_state, _ = use_provider(container, app_provider)
    return tokens.get("access_token", None) != None and app_state()['auth_user'] is not None