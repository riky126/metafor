from metafor.http import Http
# Import the interceptor functions
from interceptors import log_request, token_interceptor, refresh_token_interceptor

# Create a client with base URL and default headers
api = Http(
    base_url="//localhost:8000/api",
    default_headers={
        "Content-Type": "application/json",
        "Authorization": ""
    }
)

def set_authorization_header(token: str):
    global api
    api.default_headers["Authorization"] = f"Bearer {token}"

# Register the interceptors right after creating the api instance
api.add_request_interceptor(log_request)
api.add_request_interceptor(token_interceptor)
api.add_error_interceptor(refresh_token_interceptor)
