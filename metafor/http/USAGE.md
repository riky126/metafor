# Metafor HTTP Client Usage Guide

The `metafor/http` library implements a robust HTTP client inspired by Axios, designed for use in Python environments running in the browser (via Pyodide). It provides features like interceptors, automatic retries, streaming support, and progress tracking.

## Table of Contents
1. [Basic Usage](#basic-usage)
2. [Request Methods](#request-methods)
3. [Configuration](#configuration)
4. [Interceptors](#interceptors)
5. [Streaming & Progress](#streaming--progress)
6. [Error Handling](#error-handling)

---

## Basic Usage

Initialize the `Http` client, optionally with a base URL and default headers.

```python
from metafor.http.client import Http

# Initialize client
http = Http(
    base_url="https://api.example.com",
    default_headers={"Authorization": "Bearer token123"}
)

# Make a request
async def fetch_data():
    try:
        response = await http.get("/users/1")
        print("User:", response.json())
    except Exception as e:
        print("Error:", e)
```

## Request Methods

Supported standard HTTP methods:

```python
# GET
response = await http.get("/items", params={"sort": "desc"})

# POST
response = await http.post("/items", data={"name": "New Item"})

# PUT
await http.put("/items/1", data={"name": "Updated Item"})

# DELETE
await http.delete("/items/1")

# PATCH
await http.patch("/items/1", data={"status": "active"})
```

## Configuration

### Retries
Configure automatic retries for failed requests.

```python
http.configure_retries(
    retries=3,
    retry_delay=1000,          # 1 second
    retry_status_codes=[500, 502, 503],
    exponential_backoff=True
)
```

### Cancellation
Use `cancellation_token` to cancel pending requests.

```python
# Create token
token = http.create_cancellation_token()

# Pass to request
task = asyncio.ensure_future(http.get("/long-task", cancellation_token=token))

# Cancel later
token.cancel("User aborted")
```

## Interceptors

Intercept requests or responses globally.

```python
# Request Interceptor
def add_auth_header(config):
    config["headers"]["X-Custom-Auth"] = "secret"
    return config

http.interceptors.request.attach(add_auth_header)

# Response Interceptor
def log_response(response):
    print(f"Status: {response.status}")
    return response

http.interceptors.response.attach(log_response)
```

## Streaming & Progress

### Download Progress
Track progress for large downloads.

```python
def on_progress(loaded, total):
    percent = (loaded / total) * 100
    print(f"Downloaded: {percent:.1f}%")

await http.get("/large-file.zip", on_download_progress=on_progress)
```

### Streaming Responses
Process data chunks as they arrive (e.g., for LLM responses).

```python
async for chunk in http.stream_get("/ai/stream"):
    print(chunk, end="")
```

## Error Handling

The client raises specific exceptions for different error scenarios.

```python
from metafor.http.exceptions import HttpError, RetryRequestError, RequestCancelledError

try:
    await http.get("/risky-endpoint")
except HttpError as e:
    print(f"HTTP Error {e.status_code}: {e.message}")
except RequestCancelledError:
    print("Request was cancelled")
```
