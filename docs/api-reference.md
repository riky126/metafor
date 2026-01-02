# API Reference

Complete API reference for the Metafor framework.

## Core APIs

### `create_signal(initial_value)`

Creates a reactive signal that can be used to manage component state.

**Parameters:**
- `initial_value`: The initial value for the signal

**Returns:**
- A tuple `(getter, setter)` where:
  - `getter`: A function that returns the current value
  - `setter`: A function that updates the value

**Example:**
<div class="feature-code" data-filename="signal_example.py">
```python
from metafor.core import create_signal

count, set_count = create_signal(0)
print(count())  # 0
set_count(5)
print(count())  # 5
```
</div>

### `t` (DOM Builder)

The `t` object provides methods for creating DOM elements.

**Example:**
<div class="feature-code" data-filename="dom_example.py">
```python
from metafor.dom import t

element = t.div(
    {"className": "container", "id": "main"},
    [t.h1({}, ["Hello, World!"])]
)
```
</div>

### `@component` Decorator

Decorator for creating reusable components.

**Example:**
<div class="feature-code" data-filename="component_example.py">
```python
from metafor.decorators import component

@component
def MyComponent():
    return t.div({}, ["My Component"])
```
</div>

### Router

The router handles navigation and routing in Metafor applications.

**Example:**
<div class="feature-code" data-filename="router_example.py">
```python
from metafor.router import Route, Router

routes = [
    Route(HomePage, page_title="Home"),
    Route(AboutPage, page_title="About")
]

router = Router(routes, initial_route="/")
```
</div>

## Coming Soon

More API documentation is being added. Check back soon for:

- Complete component API
- Router API reference
- Context API
- Form handling
- HTTP client
- Storage utilities

