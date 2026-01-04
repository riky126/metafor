import asyncio
import re
from typing import Optional
from js import console
from pyodide.ffi import to_js

is_refreshing = False
request_queue = [] # Consider using asyncio.Queue for more robust handling

async def refresh_token_interceptor(error_data):
    # Import refresh_token *inside* the function where it's needed
    from services import refresh_token, local_storage
    from api_client import set_authorization_header
    
    global is_refreshing, request_queue

    original_config = error_data.get("config", {})
    response_data = error_data.get("response", {})
    status = response_data.get("status")
    
    original_url = original_config.get("_request_url")

    if not is_auth_endpoint(original_url) and status == 401 and not original_config.get("_retry_request"):
        original_config["_retry_request"] = True

        # --- Simplified Queuing Logic ---
        # Create a future that represents the completion of the token refresh
        refresh_complete_future = asyncio.Future()

        # Add the original request's config and the future to the queue
        request_queue.append({
            "config": original_config,
            "url": original_url,
            "future": refresh_complete_future,
            "original_error": error_data
        })

        # --- End Simplified Queuing ---

        if not is_refreshing:
            is_refreshing = True
            print("Token expired, attempting refresh...")
            try:
                # --- Perform Token Refresh ---
                # Call the actual refresh_token service function
                
                token_result = await refresh_token() # Assumes it returns True/False or raises/returns HttpError
                set_authorization_header(token_result.access)

                stored_tokens = local_storage.load("access_tokens")
                stored_tokens["access_token"] = token_result.access
                local_storage.save("access_tokens", stored_tokens)

                # Assuming refresh_token updated the header via set_authorization_header
                # We don't strictly need the new token here if set_authorization_header worked globally on the api instance
                print("Token refreshed successfully.")
                # --- End Token Refresh ---

                is_refreshing = False
                # Process queued requests successfully
                processed_requests = []
                while request_queue:
                    request = request_queue.pop(0)
                    # The header should already be updated globally by refresh_token -> set_authorization_header
                    # We just need to tell the client to retry this request config
                    # Add a flag to signal retry to the HTTP client's main loop
                    # Remove the interceptor retry flag so it can be caught again if needed later
                    # req["config"].pop("_retry", None) # Or keep it if needed
                    
                    # Handle JsProxy objects for headers (config is a dict)
                    config = request.get('config')
                    if config:
                        headers = config.get('headers')
                        # if headers:
                            # if isinstance(headers, dict):
                            #     print("Updating Authorization header in queued request 1")
                            #     headers["Authorization"] = f"Bearer {token_result.access}"
                            # else:
                            #     # Assume JsProxy
                        print("Updating Authorization header in queued request")
                        setattr(headers, "Authorization", f"Bearer {token_result.access}")
                    
                    request['future'].set_result({"url": request["url"], 
                                                  "config": request["config"], 
                                                  "_retry_request": True})
                    
                    processed_requests.append(request) # Keep track if needed

                # Return the result for the *first* request that triggered the refresh
                if processed_requests:
                    return processed_requests[0]['future'].result()
                else:
                    # Should not happen if the triggering request was queued
                    print("Warning: Refresh triggered but no request found in queue to retry.")
                    return error_data # Fallback to original error


            except Exception as refresh_error:
                print(f"Token refresh failed: {refresh_error}")
                is_refreshing = False
                
                while request_queue:
                     req = request_queue.pop(0)
                     # Modify the original error data slightly for clarity
                     req["original_error"]["message"] = f"Token refresh failed: {refresh_error}"
                     # Resolve with the original error data, potentially modified
                     req['future'].set_result(req["original_error"])

                # Return the modified error data for the request that triggered the refresh
                error_data["message"] = f"Token refresh failed: {refresh_error}"

                # Ensure the original error is attached if it came from refresh_token
                if isinstance(refresh_error, Exception) and not error_data.get("original_error"):
                     error_data["original_error"] = refresh_error
                return error_data # Return original error data (or modified)

        else:
            # Refresh already in progress, return the future to wait on
            print("Refresh in progress, request will wait...")
            # The request that triggered this specific interceptor call should be the last one added
            if request_queue:
                 # Find the future associated with the current request's config
                 current_future = None
                 for req in reversed(request_queue): # Search backwards likely faster
                      if req["config"] is original_config: # Check object identity
                           current_future = req["future"]
                           break
                 if current_future:
                      return await current_future
                 else:
                      # Should not happen if queuing logic is correct
                      print("Error: Refresh in progress but current request's future not found in queue.")
                      error_data["message"] = "Token refresh in progress, but queue state inconsistent for this request."
                      return error_data
            else:
                 # Should not happen, but handle defensively
                 print("Error: Refresh in progress but request queue is empty.")
                 error_data["message"] = "Token refresh in progress, but queue state inconsistent."
                 return error_data

    # If not a 401 or already retried by this interceptor, just pass the error data along
    return error_data


def log_request(request_config):
    return request_config

def token_interceptor(request_config):
    return request_config

def is_auth_endpoint(url: Optional[str]) -> bool:
    if not isinstance(url, str):
        # Return False if the input is None or not a string
        return False
    pattern = r'/login|/refresh'
    return re.search(pattern, url, re.IGNORECASE) is not None
