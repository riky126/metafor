from metafor.http import Http
# Import the interceptor functions
from interceptors import log_request, token_interceptor, refresh_token_interceptor

# Create a client with base URL and default headers
http_client = Http(
    base_url="//localhost:8000/api",
    default_headers={
        "Content-Type": "application/json",
        "Authorization": ""
    }
)

def set_authorization_header(token: str):
    global http_client
    http_client.default_headers["Authorization"] = f"Bearer {token}"

# Register the interceptors right after creating the api instance
http_client.interceptors.request.attach(log_request)
http_client.interceptors.response.attach(token_interceptor)
http_client.interceptors.error.attach(refresh_token_interceptor)