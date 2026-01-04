import json
import asyncio
from js import fetch, FormData, Uint8Array, console
from pyodide.ffi import to_js, JsProxy
from typing import Dict, Any, Optional, Callable, AsyncGenerator, Tuple, List, Union

from .cookie import CookieManager
from .exceptions import HttpError, RetryRequestError, RequestCancelledError
from .support import RetryConfig, ProgressTracker, CancellationToken

class Http:
    """
        A Metafor/Pyodide HTTP client inspired by axios.
        Provides a simple interface for making HTTP requests from Python code running in the browser.
    """

    def __init__(self, base_url: str = "", default_headers: Dict[str, str] = None, with_credentials: bool = False):
        """
        Initialize the HTTP client.

        Args:
            base_url: The base URL to prepend to all request URLs
            default_headers: Default headers to include with every request
            with_credentials: Whether to send cookies with cross-origin requests
        """
        self.base_url = base_url
        self.with_credentials = with_credentials
        self.default_headers = default_headers or {
            "Content-Type": "application/json"
        }
        self.interceptors = {
            "request": [],
            "response": [],
            "error": []
        }
        self.cookie_manager = CookieManager()
        self.default_retry_config = RetryConfig()

    def _get_full_url(self, url: str) -> str:
        """Combine base URL with the provided endpoint URL"""
        if url.startswith("http://") or url.startswith("https://"):
            return url
        return f"{self.base_url.rstrip('/')}/{url.lstrip('/')}"

    def _prepare_headers(self, headers: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        """Merge default headers with request-specific headers"""
        result = dict(self.default_headers)

        # Add cookie header if we have cookies
        cookie_header = self.cookie_manager.get_cookie_header()
        if cookie_header:
            result["Cookie"] = cookie_header

        if headers:
            result.update(headers)

        return result

    def _prepare_data(self, data: Any, headers: Dict[str, str]) -> Tuple[Any, Optional[int]]:
        """Prepare data for sending based on content type and return total size if possible"""
        content_type = headers.get("Content-Type", "").lower()
        total_size = None

        if data is None:
            return None, None

        if "application/json" in content_type:
            json_str = json.dumps(data)
            total_size = len(json_str)
            return json_str, total_size
        elif "multipart/form-data" in content_type:
            # Remove the content-type header as fetch will set it with the boundary
            if "Content-Type" in headers:
                 del headers["Content-Type"] # Check existence before deleting

            form_data = FormData.new()
            for key, value in data.items():
                # TODO: Handle file uploads (value might be File object)
                form_data.append(key, str(value))
            # Can't determine size for FormData reliably
            return form_data, None
        elif "application/octet-stream" in content_type and isinstance(data, bytes):
            total_size = len(data)
            return Uint8Array.from_py(data), total_size

        # For string data
        if isinstance(data, str):
            total_size = len(data)

        # Fallback: return data as is
        return data, total_size

    async def _track_request_body_upload(self, data, progress_callback):
        """
            Create a ReadableStream that tracks upload progress of the request body.
            This is a simplified version as browser fetch API doesn't directly expose upload progress.
        """
        if isinstance(data, str):
            data_bytes = data.encode('utf-8')
        elif isinstance(data, bytes):
            data_bytes = data
        else:
            # Can't track non-string/bytes data
            return data

        total_size = len(data_bytes)
        # chunk_size = 16384  # 16KB chunks - Not used in current simplified version
        progress_tracker = ProgressTracker(total_size)
        if progress_callback:
            progress_tracker.add_callback(progress_callback)
            # Simulate progress completion immediately as we don't have real tracking
            progress_tracker.update(total_size)

        # Return the original data for now - future implementations could use
        # ReadableStream but it's complex to integrate with fetch in pyodide
        return data

    async def request(self, method: str, url: str,
                      data: Any = None,
                      params: Dict[str, str] = None,
                      headers: Dict[str, str] = None,
                      timeout: int = 0,
                      stream: bool = False,
                      on_upload_progress: Callable = None,
                      on_download_progress: Callable = None,
                      cancellation_token: CancellationToken = None,
                      retry_config: Union[RetryConfig, bool] = None,
                      with_credentials: bool = None) -> Dict[str, Any]:
        """
        Make an HTTP request.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE, etc.)
            url: The URL to send the request to
            data: Data to include in the request body
            params: URL parameters to include in the request
            headers: Headers to include in the request
            timeout: Request timeout in milliseconds (0 means no timeout)
            stream: Whether to stream the response data
            on_upload_progress: Callback for tracking upload progress
            on_download_progress: Callback for tracking download progress
            cancellation_token: Token for cancelling the request
            retry_config: Configuration for request retries or True to use default
            with_credentials: Whether to send cookies with cross-origin requests (overrides instance default)

        Returns:
            Response object with data, status, headers, etc.
        """
        # Process request URL
        full_url = self._get_full_url(url)

        # Add query parameters if provided
        if params:
            param_strings = []
            for key, value in params.items():
                # Basic URL encoding might be needed here for robustness
                param_strings.append(f"{key}={value}")
            param_string = "&".join(param_strings)
            full_url = f"{full_url}{'?' if '?' not in full_url else '&'}{param_string}"

        # Prepare headers (make a copy to avoid modifying defaults during _prepare_data)
        request_headers = self._prepare_headers(headers)

        # Prepare request config
        config = {
            "method": method.upper(),
            # Pass a copy of headers to to_js, as _prepare_data might modify the original dict
            "headers": to_js(request_headers.copy()),
            # Store original python headers for potential use in interceptors/errors
            "_py_headers": request_headers.copy()
        }

        # Add timeout if specified
        if timeout > 0:
            # fetch uses milliseconds
            config["timeout"] = timeout

        # Add cancellation support if token provided
        if cancellation_token:
            config["signal"] = cancellation_token.get_signal()

        # Handle with_credentials
        should_use_credentials = self.with_credentials if with_credentials is None else with_credentials
        if should_use_credentials:
            config["credentials"] = "include"

        # Prepare and add data if needed for this request method
        if method.upper() not in ["GET", "HEAD"] and data is not None:
            # Pass the mutable request_headers dict here so _prepare_data can modify it (e.g., remove Content-Type for FormData)
            prepared_data, total_size = self._prepare_data(data, request_headers)

            # Update headers in config if they were modified (e.g., Content-Type removed)
            config["headers"] = to_js(request_headers)
            config["_py_headers"] = request_headers # Keep python version updated

            # Set up upload progress tracking if callback provided
            if on_upload_progress:
                 # Use the simplified tracking for now
                 await self._track_request_body_upload(prepared_data, on_upload_progress)
                 # Note: prepared_data itself isn't modified by _track_request_body_upload currently

            config["body"] = prepared_data

        # Determine retry configuration
        active_retry_config = None
        if retry_config is True:
            active_retry_config = self.default_retry_config
        elif isinstance(retry_config, RetryConfig):
            active_retry_config = retry_config
        elif retry_config is False: # Explicitly disable retries
             active_retry_config = None
        else: # Default behavior if None or not specified
             active_retry_config = self.default_retry_config

        # Apply request interceptors
        # The interceptor receives and returns a dict like {"url": ..., "config": ...}
        # where "config" is the dictionary passed to fetch
        current_request_config = {"url": full_url, "config": config}
        try:
            for interceptor in self.interceptors["request"]:
                returned_config = await self._run_interceptor(interceptor, current_request_config)
                # Allow interceptors to return None or the modified config
                current_request_config = returned_config if returned_config is not None else current_request_config
                if not isinstance(current_request_config, dict) or "url" not in current_request_config or "config" not in current_request_config:
                     raise ValueError("Request interceptor must return a dictionary with 'url' and 'config' keys, or None.")

        except Exception as e:
            # Handle request interceptor errors
            error_data = {
                "message": f"Request interceptor error: {str(e)}",
                "original_error": e,
                "phase": "request_interceptor",
                "config": config # Use original config for error context
            }
            # Apply error interceptors (though unlikely to retry from here)
            for error_interceptor in self.interceptors["error"]:
                try:
                    error_data = await self._run_interceptor(error_interceptor, error_data)
                    # If interceptor signals retry (unlikely here, but for consistency)
                    if isinstance(error_data, dict) and error_data.get("_retry_request", False):
                         current_request_config = error_data
                         # This path is less common, usually retry happens after a failed fetch
                         break # Exit interceptor loop, proceed to fetch attempt
                except Exception as inner_e:
                    console.error(f"Error in error interceptor during request phase: {str(inner_e)}")
            else: # Only raise if no interceptor signaled retry
                 raise HttpError(error_data)
            # If retry was signaled, current_request_config is updated, fall through to fetch

        # Retry loop
        attempt = 0
        # Use retries from active_retry_config if available, otherwise just 1 attempt
        max_attempts = (active_retry_config.retries + 1) if active_retry_config else 1

        last_error_data = None # Store the last error in case all retries fail

        while attempt < max_attempts:
            try:
                # Check if request has been cancelled before fetching
                if cancellation_token and cancellation_token.is_cancelled:
                    err = type("AbortError", (Exception,), {"name": "AbortError"})("Request was cancelled before fetch")
                    raise err # Raise cancellation error

                # Add internal flag to config for interceptors to check if it's a retry
                current_request_config["config"]["_is_retry_attempt"] = attempt > 0
                # Store the request URL in the config for easier access in interceptors
                current_request_config["config"]["_request_url"] = current_request_config["url"]

                # Make the request using the potentially modified config
                response = await fetch(current_request_config["url"], **current_request_config["config"])

                # Process Set-Cookie headers
                if 'Set-Cookie' in response.headers:
                    self._process_set_cookie_headers(response.headers.getAll('Set-Cookie'))

                # --- Response Handling (Streaming, Download Progress, Parsing) ---
                # Assume 'result' is built here containing parsed data, status, headers etc.
                content_type = response.headers.get("Content-Type", "")
                if stream:
                     result = await self._handle_streaming_response(response, current_request_config['config'], on_download_progress)
                elif on_download_progress:
                     result = await self._handle_download_progress(response, current_request_config['config'], on_download_progress)
                else:
                    # Simplified parsing logic for example
                    data = None
                    try:
                        if "application/json" in content_type:
                            data = await response.json()
                        elif "text/" in content_type:
                            data = await response.text()
                        else:
                            buffer = await response.arrayBuffer()
                            data = bytes(Uint8Array.new(buffer))
                    except Exception as parse_error:
                         # Handle cases where parsing fails (e.g., invalid JSON)
                         console.warn(f"Failed to parse response body: {parse_error}")
                         # Try reading as text or bytes as fallback
                         try:
                             buffer = await response.arrayBuffer() # Need to re-read if first attempt consumed body
                             data = bytes(Uint8Array.new(buffer))
                         except Exception:
                              data = None # Could not read body

                    result = {
                        "data": data,
                        "status": response.status,
                        "statusText": response.statusText,
                        "headers": dict(response.headers),
                        "config": current_request_config['config'],
                        "request": response # Keep original response object if needed
                    }
                # --- End Response Handling ---

                # Apply response interceptors
                try:
                    for interceptor in self.interceptors["response"]:
                        result = await self._run_interceptor(interceptor, result)
                except Exception as e:
                    # Handle response interceptor errors
                    last_error_data = {
                        "message": f"Response interceptor error: {str(e)}",
                        "original_error": e,
                        "phase": "response_interceptor",
                        "response": result, # Pass the result from previous steps
                        "config": current_request_config['config']
                    }
                    # Apply error interceptors
                    for error_interceptor in self.interceptors["error"]:
                        try:
                            last_error_data = await self._run_interceptor(error_interceptor, last_error_data)
                            # Check if error interceptor handled it and wants to retry
                            if isinstance(last_error_data, dict) and last_error_data.get("_retry_request", False):
                                current_request_config = last_error_data
                                # Need to break the outer loop and restart the attempt
                                raise RetryRequestError() # Use a custom signal exception
                        except RetryRequestError:
                             raise # Propagate signal
                        except Exception as inner_e:
                            console.error(f"Error in error interceptor during response phase: {str(inner_e)}")
                    # If no retry signal, raise the error from the response interceptor
                    raise HttpError(last_error_data)


                # Check for HTTP error status codes (4xx or 5xx)
                if 400 <= response.status < 600:
                    error_data_http = {
                        "message": f"Request failed with status code {response.status}",
                        "response": result, # Include the processed result
                        "config": current_request_config['config'],
                        "phase": "http_status_error"
                    }
                    last_error_data = error_data_http # Store this as the potential final error

                    # --- Standard Retry Logic (for transient errors) ---
                    # Check if standard retry is configured and applicable
                    should_standard_retry = (
                        active_retry_config and
                        active_retry_config.should_retry(response.status, method, attempt) and
                        not current_request_config['config'].get("_interceptor_retried") # Avoid standard retry if already an interceptor retry
                    )

                    if should_standard_retry:
                        attempt += 1
                        if attempt < max_attempts: # Only sleep if there's another attempt
                             delay_ms = active_retry_config.get_delay(attempt - 1)
                             # Call retry callback if provided
                             if active_retry_config.on_retry:
                                 try:
                                     await self._run_interceptor(active_retry_config.on_retry, { # Use await helper
                                         "attempt": attempt,
                                         "url": current_request_config['url'],
                                         "method": method,
                                         "status": response.status,
                                         "retry_delay": delay_ms,
                                         "config": current_request_config['config']
                                     })
                                 except Exception as cb_error:
                                     console.error(f"Error in standard retry callback: {str(cb_error)}")
                             await asyncio.sleep(delay_ms / 1000)
                             continue # Go to the next iteration of the while loop for standard retry
                        else:
                             # Max standard attempts reached, fall through to error interceptors
                             pass

                    interceptor_handled_error = False
                    current_request_config['config']["_interceptor_retried"] = False # Reset flag

                    for error_interceptor in self.interceptors["error"]:
                        try:
                            # Pass the HTTP error data to the interceptor
                            returned_value = await self._run_interceptor(error_interceptor, error_data_http.copy()) # Pass a copy

                            # *** KEY CHANGE: Check if interceptor returned a config for retry ***
                            if isinstance(returned_value, dict) and returned_value.get("_retry_request", False):
                                console.log("Interceptor requested retry. Updating config and continuing.")
                                current_request_config = returned_value # Update config for the next attempt
                                # Mark that an interceptor retry happened
                                current_request_config['config']["_interceptor_retried"] = True
                                # Reset attempt counter *if* the interceptor handles it,
                                # or manage attempts within the interceptor logic.
                                # For simplicity here, we just continue the loop.
                                # The interceptor should ensure it doesn't loop infinitely (e.g., using _retry_request flag).
                                interceptor_handled_error = True
                                break # Exit interceptor loop, the while loop will continue

                            # Otherwise, the interceptor might have modified the error data
                            error_data_http = returned_value
                            # Ensure it's still a dict, otherwise treat as unhandled
                            if not isinstance(error_data_http, dict):
                                 console.error("Error interceptor returned non-dict value, cannot proceed.")
                                 # Restore original error data before raising
                                 error_data_http = last_error_data
                                 interceptor_handled_error = False
                                 break


                        except Exception as inner_e:
                            console.error(f"Error within error interceptor itself: {str(inner_e)}")
                            # Store the interceptor error, potentially overriding the HTTP error
                            last_error_data = {
                                "message": f"Error interceptor failed: {str(inner_e)}",
                                "original_error": inner_e,
                                "phase": "error_interceptor_exception",
                                "config": current_request_config['config'],
                                "previous_error": error_data_http # Include the error it was trying to handle
                            }
                            # Stop processing further interceptors on this error if one fails critically
                            interceptor_handled_error = False # Mark as not handled for retry
                            break

                    if interceptor_handled_error:
                        # Interceptor signaled retry, continue to next iteration of the main while loop
                        attempt += 1 # Increment attempt count after interceptor retry signal
                        continue

                    # If we reach here after checking status code, it means:
                    # 1. It was an HTTP error (4xx/5xx)
                    # 2. Standard retry logic (if applicable) didn't continue or was exhausted.
                    # 3. Error interceptors ran, but none signaled a retry.
                    # So, raise the last known error (potentially modified by interceptors).
                    raise HttpError(last_error_data)


                # If status code was not 4xx/5xx, request was successful
                return result # Return successful result

            except RetryRequestError: # Catch the signal from response interceptor error handling
                attempt += 1
                console.log("Retrying after response interceptor error handling.")
                continue # Continue the while loop

            except Exception as e:
                # Handle non-HTTP errors (network errors, cancellation, etc.)

                # Check for cancellation first
                is_abort_error = hasattr(e, "name") and e.name == "AbortError"
                if is_abort_error or isinstance(e, RequestCancelledError):
                    # Don't retry cancellations, just raise
                    raise RequestCancelledError({
                        "message": "Request was cancelled",
                        "original_error": e,
                        "phase": "cancellation",
                        "config": current_request_config.get('config', {}) # Safely get config
                    }) from e

                # Store this as the last error
                last_error_data = {
                    "message": f"Request execution error: {str(e)}",
                    "original_error": e,
                    "phase": "request_execution",
                    "config": current_request_config.get('config', {}) # Safely get config
                }

                # --- Standard Retry Logic for Network Errors ---
                # You might want specific conditions here, e.g., check error type
                should_standard_retry_network = (
                    active_retry_config and
                    # Use -1 status for network error, check if method is retryable
                    active_retry_config.should_retry(-1, method, attempt) and
                    not current_request_config['config'].get("_interceptor_retried")
                )

                if should_standard_retry_network:
                    attempt += 1
                    if attempt < max_attempts:
                        delay_ms = active_retry_config.get_delay(attempt - 1)
                        if active_retry_config.on_retry:
                             try:
                                 await self._run_interceptor(active_retry_config.on_retry, { # Use await helper
                                     "attempt": attempt,
                                     "url": current_request_config['url'],
                                     "method": method,
                                     "error": str(e),
                                     "retry_delay": delay_ms,
                                     "config": current_request_config['config']
                                 })
                             except Exception as cb_error:
                                 console.error(f"Error in standard network retry callback: {str(cb_error)}")
                        await asyncio.sleep(delay_ms / 1000)
                        continue # Retry the request attempt

                # --- Error Interceptor Logic for Network/Execution Errors ---
                interceptor_handled_error = False
                current_request_config['config']["_interceptor_retried"] = False # Reset flag
                for error_interceptor in self.interceptors["error"]:
                    try:
                        returned_value = await self._run_interceptor(error_interceptor, last_error_data.copy()) # Pass a copy

                        # Check if interceptor handled it and wants to retry
                        if isinstance(returned_value, dict) and returned_value.get("_retry_request", False):
                            console.log("Interceptor requested retry for execution error.")
                            current_request_config = returned_value
                            current_request_config['config']["_interceptor_retried"] = True
                            interceptor_handled_error = True
                            break # Exit interceptor loop

                        last_error_data = returned_value # Update error data if modified
                        # Ensure it's still a dict
                        if not isinstance(last_error_data, dict):
                             console.error("Error interceptor returned non-dict value, cannot proceed.")
                             last_error_data = { # Reconstruct basic error
                                "message": f"Request execution error: {str(e)}",
                                "original_error": e, "phase": "request_execution",
                                "config": current_request_config.get('config', {})
                             }
                             interceptor_handled_error = False
                             break


                    except Exception as inner_e:
                        console.error(f"Error within error interceptor itself during execution phase: {str(inner_e)}")
                        last_error_data = {
                            "message": f"Error interceptor failed during execution phase: {str(inner_e)}",
                            "original_error": inner_e,
                            "phase": "error_interceptor_exception",
                            "config": current_request_config.get('config', {}),
                            "previous_error": last_error_data
                        }
                        interceptor_handled_error = False
                        break

                if interceptor_handled_error:
                    attempt += 1 # Increment attempt count after interceptor retry signal
                    continue # Continue to next iteration of the while loop

                # If no retry happened (standard or interceptor), raise the last error
                raise HttpError(last_error_data)

        # If the loop finishes without returning or raising (e.g., max attempts reached), raise the last error encountered.
        if last_error_data:
             # Ensure the last error is an HttpError instance
             if not isinstance(last_error_data, HttpError):
                 raise HttpError(last_error_data)
             else:
                 raise last_error_data
        else:
             # Should not happen in normal flow, but as a fallback
             raise HttpError({
                 "message": "Request failed after maximum attempts without specific error.",
                 "config": current_request_config.get('config', {}),
                 "phase": "max_attempts_reached"
             })


    async def _run_interceptor(self, interceptor_func, data):
        """Helper to run an interceptor, supporting both sync and async functions."""
        if asyncio.iscoroutinefunction(interceptor_func):
            return await interceptor_func(data)
        else:
            # Run sync function in default executor if needed, though interceptors
            # are often simple enough not to block significantly.
            # For simplicity, call directly. If blocking IO happens in sync interceptors,
            # consider running in executor.
            return interceptor_func(data)

    def _process_set_cookie_headers(self, set_cookie_headers):
        """Process Set-Cookie headers from the response"""
        if not set_cookie_headers:
            return

        # Ensure it's a list (JsProxy might return single string or list)
        if isinstance(set_cookie_headers, str):
             set_cookie_headers = [set_cookie_headers]
        elif isinstance(set_cookie_headers, JsProxy):
             # Attempt conversion if it's proxying a list-like object
             try:
                 set_cookie_headers = list(set_cookie_headers)
             except TypeError:
                 # If it's not iterable (e.g., proxying a single string), wrap in list
                 set_cookie_headers = [str(set_cookie_headers)]


        for cookie_str in set_cookie_headers:
            if not isinstance(cookie_str, str): # Ensure items are strings
                 cookie_str = str(cookie_str)
            try:
                # Parse the Set-Cookie header
                parts = cookie_str.split(';')
                if not parts: continue
                name_value = parts[0].strip()
                if '=' not in name_value: continue # Skip invalid format
                name, value = name_value.split('=', 1)

                # Parse cookie options
                options = {}
                for part in parts[1:]:
                    part = part.strip()
                    if not part: continue
                    if '=' in part:
                        opt_name, opt_value = part.split('=', 1)
                        options[opt_name.lower()] = opt_value
                    else:
                        options[part.lower()] = True

                # Store the cookie
                self.cookie_manager.set_cookie(name, value, options)
            except Exception as e:
                console.warn(f"Error processing Set-Cookie header '{cookie_str[:50]}...': {str(e)}")

    async def _handle_streaming_response(self, response, config, progress_callback=None):
        """Handle a streaming response with optional progress tracking"""
        if not response.body:
            raise HttpError({
                "message": "Stream requested but response has no body",
                "config": config,
                "response": { # Create a minimal response dict for the error
                     "status": response.status,
                     "statusText": response.statusText,
                     "headers": dict(response.headers),
                }
            })

        # Get content length for progress if available
        content_length = response.headers.get('Content-Length')
        total_size = int(content_length) if content_length and content_length.isdigit() else None

        # Create progress tracker if callback provided
        progress_tracker = None
        if progress_callback and total_size is not None and total_size > 0:
            progress_tracker = ProgressTracker(total_size)
            progress_tracker.add_callback(progress_callback)

        # Create a streaming response object
        streaming_response = {
            "status": response.status,
            "statusText": response.statusText,
            "headers": dict(response.headers),
            "config": config,
            "request": response, # Keep original response object
            "stream": self._create_stream_reader(response.body, progress_tracker)
        }

        return streaming_response

    async def _handle_download_progress(self, response, config, progress_callback):
        """Handle tracking download progress for non-streaming responses"""
        if not response.body:
            # No body to track, proceed with normal response handling
            content_type = response.headers.get("Content-Type", "")
            data = None
            try:
                if "application/json" in content_type:
                    data = await response.json()
                elif "text/" in content_type:
                    data = await response.text()
                else:
                    buffer = await response.arrayBuffer()
                    data = bytes(Uint8Array.new(buffer))
            except Exception as parse_error:
                 console.warn(f"Failed to parse response body (no progress tracking): {parse_error}")
                 data = None # Could not read body

            result = {
                "data": data,
                "status": response.status,
                "statusText": response.statusText,
                "headers": dict(response.headers),
                "config": config,
                "request": response
            }
            return result

        # Get content length for progress if available
        content_length = response.headers.get('Content-Length')
        total_size = int(content_length) if content_length and content_length.isdigit() else None

        # Create progress tracker
        progress_tracker = None
        if total_size is not None and total_size > 0:
             progress_tracker = ProgressTracker(total_size)
             if progress_callback:
                 progress_tracker.add_callback(progress_callback)
        elif progress_callback:
             # Callback provided but no total size, track loaded bytes only
             progress_tracker = ProgressTracker(0) # Total size unknown
             progress_tracker.add_callback(progress_callback)


        # Read the entire response with progress tracking
        content_type = response.headers.get("Content-Type", "")
        reader = response.body.getReader()
        chunks = []
        loaded_size = 0

        try:
            while True:
                result_read = await reader.read() # Use different variable name
                if result_read.done:
                    break

                # result_read.value is Uint8Array
                chunk_bytes = bytes(result_read.value)
                chunks.append(chunk_bytes)
                loaded_size += len(chunk_bytes)

                # Update progress
                if progress_tracker:
                    progress_tracker.update(len(chunk_bytes))

        finally:
            reader.releaseLock()

        # Combine chunks and parse based on content type
        all_bytes = b''.join(chunks)
        data = None
        try:
            if "application/json" in content_type:
                data = json.loads(all_bytes.decode('utf-8'))
            elif "text/" in content_type:
                # Try decoding with utf-8, fallback to latin-1 or ignore errors
                try:
                    data = all_bytes.decode('utf-8')
                except UnicodeDecodeError:
                    try:
                         data = all_bytes.decode('latin-1')
                    except:
                         data = all_bytes.decode('utf-8', errors='ignore')
            else:
                data = all_bytes
        except Exception as parse_error:
             console.warn(f"Failed to parse response body after download: {parse_error}")
             data = all_bytes # Return raw bytes if parsing failed

        # Build response object
        result = {
            "data": data,
            "status": response.status,
            "statusText": response.statusText,
            "headers": dict(response.headers),
            "config": config,
            "request": response
        }

        return result

    async def _create_stream_reader(self, body: JsProxy, progress_tracker=None) -> AsyncGenerator[bytes, None]:
        """Create a Python async generator from a JavaScript ReadableStream with optional progress tracking"""
        reader = body.getReader()

        async def stream_generator():
            try:
                while True:
                    result_read = await reader.read() # Use different variable name
                    if result_read.done:
                        break

                    # Convert the Uint8Array to Python bytes
                    chunk = bytes(result_read.value)

                    # Update progress if tracker provided
                    if progress_tracker:
                        progress_tracker.update(len(chunk))

                    yield chunk
            finally:
                reader.releaseLock()

        return stream_generator()

    # Create cancellation token
    def create_cancellation_token(self) -> CancellationToken:
        """Create a new cancellation token for request cancellation"""
        return CancellationToken()

    # Configure global retry settings
    def configure_retries(self,
                          retries: int = 2,
                          retry_delay: int = 1000,
                          exponential_backoff: bool = True,
                          retry_status_codes: List[int] = None,
                          retry_methods: List[str] = None,
                          on_retry: Callable = None) -> None:
        """
        Configure the default retry behavior for all requests.

        Args:
            retries: Maximum number of retry attempts
            retry_delay: Base delay between retries in milliseconds
            exponential_backoff: Whether to use exponential backoff for delays
            retry_status_codes: HTTP status codes that trigger a retry (-1 for network errors)
            retry_methods: HTTP methods that can be retried
            on_retry: Callback function called before each retry attempt (can be async)
        """
        self.default_retry_config = RetryConfig(
            retries=retries,
            retry_delay=retry_delay,
            exponential_backoff=exponential_backoff,
            retry_status_codes=retry_status_codes, # Uses default if None
            retry_methods=retry_methods, # Uses default if None
            on_retry=on_retry
        )

    # Streaming convenience methods with cancellation and retry support
    async def stream_get(self, url: str, params: Dict[str, str] = None,
                         headers: Dict[str, str] = None, timeout: int = 0,
                         on_download_progress: Callable = None,
                         cancellation_token: CancellationToken = None,
                         retry_config: Union[RetryConfig, bool, None] = None,
                         with_credentials: bool = None) -> Dict[str, Any]:

        """Perform a streaming GET request with cancellation and retry support"""
        return await self.request("GET", url, params=params, headers=headers,
                                  timeout=timeout, stream=True,
                                  on_download_progress=on_download_progress,
                                  cancellation_token=cancellation_token,
                                  retry_config=retry_config,
                                  with_credentials=with_credentials)

    async def stream_post(self, url: str, data: Any = None, params: Dict[str, str] = None,
                          headers: Dict[str, str] = None, timeout: int = 0,
                          on_upload_progress: Callable = None,
                          on_download_progress: Callable = None,
                          cancellation_token: CancellationToken = None,
                          retry_config: Union[RetryConfig, bool, None] = None,
                          with_credentials: bool = None) -> Dict[str, Any]:

        """Perform a streaming POST request with cancellation and retry support"""
        return await self.request("POST", url, data=data, params=params,
                                  headers=headers, timeout=timeout, stream=True,
                                  on_upload_progress=on_upload_progress,
                                  on_download_progress=on_download_progress,
                                  cancellation_token=cancellation_token,
                                  retry_config=retry_config,
                                  with_credentials=with_credentials)

    # Convenience methods for different HTTP verbs with progress tracking, cancellation and retry
    async def get(self, url: str, params: Dict[str, str] = None,
                  headers: Dict[str, str] = None, timeout: int = 0,
                  on_download_progress: Callable = None,
                  cancellation_token: CancellationToken = None,
                  retry_config: Union[RetryConfig, bool, None] = None,
                  with_credentials: bool = None) -> Dict[str, Any]:

        """Perform a GET request with optional download progress tracking, cancellation and retry"""
        return await self.request("GET", url, params=params, headers=headers,
                                  timeout=timeout,
                                  on_download_progress=on_download_progress,
                                  cancellation_token=cancellation_token,
                                  retry_config=retry_config,
                                  with_credentials=with_credentials)

    async def post(self, url: str, data: Any = None, params: Dict[str, str] = None,
                   headers: Dict[str, str] = None, timeout: int = 0,
                   on_upload_progress: Callable = None,
                   on_download_progress: Callable = None,
                   cancellation_token: CancellationToken = None,
                   retry_config: Union[RetryConfig, bool, None] = None,
                   with_credentials: bool = None) -> Dict[str, Any]:

        """Perform a POST request with optional progress tracking, cancellation and retry"""
        return await self.request("POST", url, data=data, params=params,
                                  headers=headers, timeout=timeout,
                                  on_upload_progress=on_upload_progress,
                                  on_download_progress=on_download_progress,
                                  cancellation_token=cancellation_token,
                                  retry_config=retry_config,
                                  with_credentials=with_credentials)

    async def put(self, url: str, data: Any = None, params: Dict[str, str] = None,
                  headers: Dict[str, str] = None, timeout: int = 0,
                  on_upload_progress: Callable = None,
                  on_download_progress: Callable = None,
                  cancellation_token: CancellationToken = None,
                  retry_config: Union[RetryConfig, bool, None] = None,
                  with_credentials: bool = None) -> Dict[str, Any]:

        """Perform a PUT request with optional progress tracking, cancellation and retry"""
        return await self.request("PUT", url, data=data, params=params,
                                  headers=headers, timeout=timeout,
                                  on_upload_progress=on_upload_progress,
                                  on_download_progress=on_download_progress,
                                  cancellation_token=cancellation_token,
                                  retry_config=retry_config,
                                  with_credentials=with_credentials)

    async def delete(self, url: str, data: Any = None, params: Dict[str, str] = None,
                     headers: Dict[str, str] = None, timeout: int = 0,
                     cancellation_token: CancellationToken = None,
                     retry_config: Union[RetryConfig, bool, None] = None,
                     with_credentials: bool = None) -> Dict[str, Any]:

        """Perform a DELETE request with cancellation and retry support"""
        return await self.request("DELETE", url, data=data, params=params,
                                  headers=headers, timeout=timeout,
                                  cancellation_token=cancellation_token,
                                  retry_config=retry_config,
                                  with_credentials=with_credentials)

    async def patch(self, url: str, data: Any = None, params: Dict[str, str] = None,
                    headers: Dict[str, str] = None, timeout: int = 0,
                    on_upload_progress: Callable = None,
                    on_download_progress: Callable = None,
                    cancellation_token: CancellationToken = None,
                    retry_config: Union[RetryConfig, bool, None] = None,
                    with_credentials: bool = None) -> Dict[str, Any]:

        """Perform a PATCH request with optional progress tracking, cancellation and retry"""
        return await self.request("PATCH", url, data=data, params=params,
                                  headers=headers, timeout=timeout,
                                  on_upload_progress=on_upload_progress,
                                  on_download_progress=on_download_progress,
                                  cancellation_token=cancellation_token,
                                  retry_config=retry_config,
                                  with_credentials=with_credentials)

    async def head(self, url: str, params: Dict[str, str] = None,
                   headers: Dict[str, str] = None, timeout: int = 0,
                   cancellation_token: CancellationToken = None,
                   retry_config: Union[RetryConfig, bool, None] = None,
                   with_credentials: bool = None) -> Dict[str, Any]:

        """Perform a HEAD request with cancellation and retry support"""
        return await self.request("HEAD", url, params=params, headers=headers,
                                  timeout=timeout,
                                  cancellation_token=cancellation_token,
                                  retry_config=retry_config,
                                  with_credentials=with_credentials)

    async def options(self, url: str, params: Dict[str, str] = None,
                      headers: Dict[str, str] = None, timeout: int = 0,
                      cancellation_token: CancellationToken = None,
                      retry_config: Union[RetryConfig, bool, None] = None,
                      with_credentials: bool = None) -> Dict[str, Any]:

        """Perform an OPTIONS request with cancellation and retry support"""
        return await self.request("OPTIONS", url, params=params, headers=headers,
                                  timeout=timeout,
                                  cancellation_token=cancellation_token,
                                  retry_config=retry_config,
                                  with_credentials=with_credentials)

    # Cookie management methods
    def set_cookie(self, name: str, value: str, options: Dict[str, Any] = None):
        """Set a cookie"""
        self.cookie_manager.set_cookie(name, value, options)

    def get_cookie(self, name: str) -> Optional[str]:
        """Get a cookie value by name"""
        return self.cookie_manager.get_cookie(name)

    def remove_cookie(self, name: str, options: Dict[str, Any] = None):
        """Remove a cookie"""
        self.cookie_manager.remove_cookie(name, options)

    def get_all_cookies(self) -> Dict[str, str]:
        """Get all cookies"""
        return self.cookie_manager.get_all_cookies()

    def clear_cookies(self):
        """Clear all cookies"""
        self.cookie_manager.clear_all_cookies()

    # Interceptors management
    def add_request_interceptor(self, fn: Callable) -> None:
        """Add a request interceptor function (can be async)"""
        if callable(fn):
            self.interceptors["request"].append(fn)

    def add_response_interceptor(self, fn: Callable) -> None:
        """Add a response interceptor function (can be async)"""
        if callable(fn):
            self.interceptors["response"].append(fn)

    def add_error_interceptor(self, fn: Callable) -> None:
        """Add an error interceptor function (can be async)"""
        if callable(fn):
            self.interceptors["error"].append(fn)

    def remove_request_interceptor(self, fn: Callable) -> None:
        """Remove a request interceptor function"""
        try:
            self.interceptors["request"].remove(fn)
        except ValueError:
            pass # Function not found

    def remove_response_interceptor(self, fn: Callable) -> None:
        """Remove a response interceptor function"""
        try:
            self.interceptors["response"].remove(fn)
        except ValueError:
            pass # Function not found

    def remove_error_interceptor(self, fn: Callable) -> None:
        """Remove an error interceptor function"""
        try:
            self.interceptors["error"].remove(fn)
        except ValueError:
            pass # Function not found

    def clear_interceptors(self) -> None:
        """Clear all interceptors"""
        self.interceptors = {
            "request": [],
            "response": [],
            "error": []
        }


# --- Helper functions (optional, could be outside the class) ---

async def async_task(async_func, *args, **kwargs):
    """Helper to run an async function as a task."""
    return asyncio.ensure_future(async_func(*args, **kwargs))

async def fetch_multiple(*request_funcs):
    """
    Run multiple HTTP request functions concurrently.
    Expects functions that return awaitables (like http.get, http.post).
    """
    # Ensure all inputs are awaitable tasks
    tasks = [asyncio.ensure_future(func) if asyncio.iscoroutine(func) else func for func in request_funcs]

    # Wait for all to complete
    # return_exceptions=True allows getting results even if some fail
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return results
