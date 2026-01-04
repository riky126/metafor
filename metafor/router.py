from enum import Enum
import re
from collections import deque
from js import window, console
from pyodide.ffi import create_proxy
from metafor.core import create_effect, create_signal, track
from metafor.decorators import component
from metafor.hooks import create_memo
from metafor.dom import t
import asyncio
import time
from inspect import iscoroutinefunction, iscoroutine
from typing import Any, Dict, Tuple, Callable, Optional, Pattern, List

from metafor.core import batch_updates

def _str_to_regex_path(path: str) -> Tuple[str, Pattern]:
    """Utility function to convert a path string to a regex pattern."""
    # Handle optional parameters (e.g., /users/:id?/:optional?)
    path = re.sub(r':(\w+)\?', r'(?P<\1>[^/]*)?', path)
    # Handle wildcards (e.g., /files/*)
    path = re.sub(r'\*', r'(?P<wildcard>.*)', path)
    regex_path = f"^{re.sub(r':(\w+)', r'(?P<\1>[^/]+)', path)}$"
    return regex_path, re.compile(regex_path)

class RouteMode(Enum):
    HASH_MODE = "hash"
    HISTORY_MODE = "history"

class Route:
    def __init__(self, component: Callable, name: str = None, page_title: str = None,
                 meta: Dict[str, Any] = {}, children: Optional[List['Route']] = None,
                 propagate: bool = False):
        if not callable(component):
            raise Exception("Component is not callable")

        self._component = component
        self._path = None
        self.name = name
        self.meta = meta
        self.page_title = page_title
        self._propagate = propagate
        self.children = self._compile_children(children) if children else {}
        self._compiled_regex = None

    @property
    def path(self) -> Pattern:
        return self._path

    @path.setter
    def path(self, path: str | Pattern):
        self._path = path
        self._compiled_regex = re.compile(path) if isinstance(path, str) else path

    @property
    def component(self):
        return self._component

    @property
    def compiled_regex(self):
        return self._compiled_regex

    def _compile_children(self, children: List['Route']) -> Dict[Pattern, 'Route']:
        compiled_children = {}
        for route in children:
            try:
                child_path = route.component.__path__
            except:
                raise Exception("'path' argument is required for page component, ensure @page('som_path') decorator called with path.")

            # Merge parent meta into child meta recursively only if propagate is True
            if self._propagate:
                route._update_meta_recursive(self.meta)
            
            normalized_path = child_path.lstrip('/')
            regex_path, regex_compiled = _str_to_regex_path(normalized_path)
            route.path = regex_path
            compiled_children[regex_compiled] = route
        return compiled_children

    def _update_meta_recursive(self, parent_meta: Dict[str, Any]):
        """Recursively update meta for this route and its children."""
        self.meta = {**parent_meta, **self.meta}
        for child in self.children.values():
            child._update_meta_recursive(self.meta)


class Router:
    # Routing modes
    HASH_MODE = RouteMode.HASH_MODE
    HISTORY_MODE = RouteMode.HISTORY_MODE

    def __init__(self, routes: List[Route], initial_route: str = "/",
                 before_hooks: Optional[List[Callable]] = None,
                 after_hooks: Optional[List[Callable]] = None,
                 mode: str = HASH_MODE, base_path: str = ""):
        
        self.routes = self._compile_routes(routes)
        self._current_component = None
        self.before_hooks = before_hooks or []
        self.after_hooks = after_hooks or []
        self.mode = mode
        self.base_path = base_path.rstrip('/')  # Remove trailing slash if present

        self.params_signal, self.set_params = create_signal({})
        self.query_signal, self.set_query = create_signal({})

        # current_route holds a dict with 'path' and 'ts' (timestamp) to support
        # same-component re-renders while allowing Link to check path equality efficiently.
        self.current_route, self.set_current_route = create_signal({"path": initial_route, "ts": time.time()})
        self.last_valid_route = None

        self.history_signal, self.set_history = create_signal(deque(maxlen=50))  # Use deque for efficient history
        self.current_history_index_signal, self.set_current_history_index = create_signal(-1)

        # Set up different event listeners based on routing mode
        if self.mode == self.HASH_MODE:
            self._route_change_proxy = create_proxy(self._handle_hash_change)
            window.addEventListener("hashchange", self._route_change_proxy)
        elif self.mode == self.HISTORY_MODE:
            self._route_change_proxy = create_proxy(self._handle_history_change)
            window.addEventListener("popstate", self._route_change_proxy)
        else:
            raise ValueError(f"Invalid routing mode: {mode}. Use 'hash' or 'history'.")

    async def intialize(self):
        """Initialize the router by handling the current URL."""
        if self.mode == self.HASH_MODE:
            await self._handle_hash_change(None)
        else:
            await self._handle_history_change(None)

    def _compile_routes(self, routes: List[Route]) -> Dict[Pattern, Route]:
        """Compile route patterns into regular expressions."""
        compiled_routes = {}
        for route in routes:
            try:
                path = route.component.__path__
            except:
                raise Exception("'path' argument is required for page component, ensure @page('som_path') decorator called with path.")
            
            normalized_path = path.lstrip('/')
            regex_path, regex_compiled = _str_to_regex_path(normalized_path)
            route.path = regex_path
            compiled_routes[regex_compiled] = route
        return compiled_routes

    def _parse_path_parameters(self, path: str, regex: Pattern) -> Dict[str, str]:
        """Extract parameters from path based on a specific route pattern."""
        match = regex.match(path)
        if not match:
            return {}
        
        params = match.groupdict()
        
        # Remove optional parameters that are not present
        for key, value in list(params.items()):
            if value == '':
                del params[key]
        
        return params

    def _parse_query_parameters(self, query_string: str) -> Dict[str, str]:
        """Parse query string into a dictionary of parameters."""
        params = {}
        if not query_string:
            return params

        pairs = query_string.split('&')
        for pair in pairs:
            if '=' not in pair:
                continue
            try:
                key, value = pair.split('=', 1)
                params[key] = value
            except Exception as e:
                console.error(f"Error parsing query parameter: {pair} - {str(e)}")
        return params

    def _get_current_path(self) -> Tuple[str, str]:
        """Get the current path and query string based on the routing mode."""
        if self.mode == self.HASH_MODE:
            hash_part = window.location.hash.replace("#", "")
            if not hash_part:
                return "/", ""

            path = hash_part
            query_string = ""
            if "?" in hash_part:
                path, query_string = hash_part.split("?", 1)
            return path, query_string
        else:  # History mode
            path = window.location.pathname
            # Remove base path if it exists
            if self.base_path and path.startswith(self.base_path):
                path = path[len(self.base_path):] or "/"

            return path, window.location.search.lstrip("?")

    def _get_route_actual_path(self, route: Route) -> Optional[str]:
        """Get the actual path string from a Route object."""
        try:
            actual_path = route.component.__path__
            # Return None if path is empty string, so fallback logic works
            return actual_path if actual_path else None
        except:
            return None

    def _is_route_under_guarded_route(self, guarded_pattern: str, matched_routes_with_params: List[Tuple[Route, Dict[str, str]]]) -> bool:
        """Check if the matched routes are under the guarded route."""
        # Find the route that matches the guard pattern
        guarded_route = None
        for pattern, route in self.routes.items():
            pattern_str = str(pattern.pattern)
            if pattern_str == guarded_pattern:
                guarded_route = route
                break
        
        if not guarded_route:
            return False
        
        # Check if any of the matched routes is the guarded route or its descendant
        for route, _ in matched_routes_with_params:
            if route == guarded_route:
                return True
            # Check if route is a descendant by checking if guarded_route has children
            # and if any matched route is in the hierarchy starting from guarded_route
            if self._is_descendant(route, guarded_route):
                return True
        
        return False

    def _is_descendant(self, route: Route, ancestor: Route) -> bool:
        """Check if route is a descendant of ancestor by traversing children."""
        if not ancestor.children:
            return False
        
        # Check direct children
        for child_regex, child_route in ancestor.children.items():
            if child_route == route:
                return True
            # Recursively check grandchildren
            if self._is_descendant(route, child_route):
                return True
        
        return False

    async def _execute_hooks(self, hooks: List[Callable], path: str, params: Optional[Dict[str, str]] = None,
                             query: Optional[Dict[str, str]] = None,
                             matched_routes: Optional[List[Tuple[Route, Dict[str, str]]]] = None,
                             stop_on_failure: bool = True) -> Tuple[bool, Optional[Any]]:
        """Execute a set of hooks (before or after) for the current path."""
        params = params or {}
        query = query or {}

        if matched_routes is None:
            matched_routes_with_params, _ = self._find_matching_route(path.lstrip('/'), self.routes)
        else:
            matched_routes_with_params = matched_routes

        if not matched_routes_with_params:
            return True, None

        prev_path = self.last_valid_route or "/"
        
        # We need the previous route object for the guard function
        prev_path_normalized = prev_path.lstrip('/')
        prev_matched_routes, _ = self._find_matching_route(prev_path_normalized, self.routes)
        prev_route_obj = prev_matched_routes[-1][0] if prev_matched_routes else None

        # Get the deepest route for guard execution
        deepest_route = matched_routes_with_params[-1][0] if matched_routes_with_params else None
        
        # Use provided path as the actual path (it's already resolved with params)
        deepest_route_path_str = path
        prev_route_path_str = prev_path

        all_params = {**params, **matched_routes_with_params[-1][1]} if matched_routes_with_params else params

        # Extract just the route objects for the hook
        raw_matched_routes = [r for r, _ in matched_routes_with_params] if matched_routes_with_params else []

        # Execute hooks in order
        for hook_fn in hooks:
            # Use original route objects and update their path attribute temporarily
            from_route = prev_route_obj
            to_route = deepest_route
            
            # Store original paths and update with actual path strings
            original_from_path = None
            original_to_path = None
            
            if from_route:
                original_from_path = from_route.path
                from_route.path = prev_route_path_str
            
            if to_route:
                original_to_path = to_route.path
                to_route.path = deepest_route_path_str
            
            # Pass matched_routes in kwargs
            hook_result = await self._execute_single_hook(hook_fn, from_route, to_route, all_params, query, raw_matched_routes)
            
            # Restore original paths
            if original_from_path is not None:
                from_route.path = original_from_path
            if original_to_path is not None:
                to_route.path = original_to_path
            
            if stop_on_failure:
                # Interpret result for blocking hooks
                if isinstance(hook_result, (str, dict)):
                    # Redirect string or dict returned
                    return False, hook_result
                elif hook_result is False:
                    # Explicit block (no redirect)
                    return False, None
                # True or None means allow -> continue loop

        return True, None

    def _resolve_redirect(self, redirect_info: Any) -> Tuple[Optional[str], Dict[str, str]]:
        """Resolve a redirect object (str or dict) to a path string and query params."""
        if isinstance(redirect_info, str):
            return redirect_info, {}
        
        if isinstance(redirect_info, dict):
            path = redirect_info.get("path")
            params = redirect_info.get("params", {})
            query = redirect_info.get("query", {})
            
            if not path:
                return None, {}
            
            pattern = None
            
            # Check if it's a named route
            named_route = self._get_route_by_name(path)
            if named_route:
                pattern, route = named_route
            else:
                # Convert path string to regex pattern using existing utility
                # Note: path provided in dict might be a pattern like "/users/:id"
                _, pattern = _str_to_regex_path(path.lstrip('/'))
            
            if pattern:
                 resolved_path = self._build_path_with_params(pattern, params)
                 if resolved_path is not None:
                     if not resolved_path.startswith('/'):
                         resolved_path = '/' + resolved_path
                     return resolved_path, query
                 # Fallback if build fails? 
                 # Maybe our regex construction doesn't strictly match _build_path expectation?
                 console.log(f"Failed to build path for {path} with params {params}")
                 
            return path, query
            
        return None, {}

    async def _execute_single_hook(self, hook_fn, prev_route, route, params, query, matched_routes):
        """Helper function to execute a hook and handle async/sync results."""
        try:
            result = hook_fn(prev_route, route, **params, **query, matched_routes=matched_routes)
            if iscoroutinefunction(hook_fn) or iscoroutine(result):
                return await result
            else:
                return result
        except Exception as e:
            console.error(f"Error executing hook: {str(e)}")
            return False

    async def _handle_hash_change(self, event) -> None:
        """Handle hash change events for hash-based routing."""
        await self._handle_route_change(event)

    async def _handle_history_change(self, event) -> None:
        """Handle popstate events for history-based routing."""
        await self._handle_route_change(event)

    async def _handle_route_change(self, event):
        """Unified handler for route changes."""
        path, query_string = self._get_current_path()
        query_params = self._parse_query_parameters(query_string)

        # Skip if already on this route (no actual route change)
        if path == self.last_valid_route:
            return

        matched_routes_with_params, _ = self._find_matching_route(path.lstrip('/'), self.routes)

        if not matched_routes_with_params:
            console.warn(f"No route matched for path: {path}")
            batch_updates(lambda: [
                self._set_route_without_navigation(path)
            ])
            return

        deepest_route, deepest_params = matched_routes_with_params[-1]

        can_access, redirect_path = await self._execute_hooks(self.before_hooks, path, deepest_params, query_params, matched_routes=matched_routes_with_params, stop_on_failure=True)

        if not can_access:
            resolved_path, resolved_query = self._resolve_redirect(redirect_path)
            if resolved_path:
                batch_updates(lambda: [
                    self._perform_redirect(resolved_path, resolved_query)
                ])
            elif self.last_valid_route and self.last_valid_route != path:
                 # Blocked without redirect (and URL changed), revert
                 self._perform_redirect(self.last_valid_route)
            else:
                 if not self.last_valid_route:
                    # Blocked on initial route with no history. 
                    # Set to None to prevent rendering anything.
                    # Note: _set_route_without_navigation handles None by updating state.
                    self.set_current_route({"path": None, "ts": time.time()})
                    self.last_valid_route = None # Ensure last valid is None
            return
        

        batch_updates(lambda: [
            self.set_params(deepest_params) if deepest_params else None,
            self.set_query(query_params) if query_params else None,
            self._set_route_without_navigation(path)
        ])
        
        # Get previous component for hooks (captured before state update if needed, but here we need route object)
        prev_route_obj = None # Need to capture this before update if not already captured
        # In this context, we don't have easy access to prev_route_obj unless we re-match.
        # But wait, we simplified logic earlier.
        
        # We need to capture previous route object for the hook
        prev_path = self.last_valid_route or "/"
        prev_matched, _ = self._find_matching_route(prev_path.lstrip('/'), self.routes)
        prev_route_obj = prev_matched[-1][0] if prev_matched else None

        # Execute after hooks
        asyncio.create_task(self._execute_hooks(self.after_hooks, path, deepest_params, matched_routes=None, stop_on_failure=False))

        if event and path != self.last_valid_route:
            self._update_history(path, query_params)


    def _set_route_without_navigation(self, path: str) -> None:
        """Update the current route without triggering navigation."""
        self.set_current_route({"path": path, "ts": time.time()})
        self.last_valid_route = path

    def _perform_redirect(self, path: str, query_params: Optional[Dict[str, str]] = None) -> None:
        """Redirect to a new route."""
        self._cleanup_current()
        matched_routes_with_params, _ = self._find_matching_route(path.lstrip('/'), self.routes)
        deepest_params = matched_routes_with_params[-1][1] if matched_routes_with_params else {}

        self.set_params(deepest_params)

        current_query = query_params if query_params is not None else self.query_signal()
        self.set_query(current_query)

        query_string = ""
        if current_query:
            query_parts = [f"{key}={value}" for key, value in current_query.items()]
            if query_parts:
                query_string = f"?{'&'.join(query_parts)}"

        self.set_current_route({"path": path, "ts": time.time()})

        if self.mode == self.HASH_MODE:
            window.removeEventListener("hashchange", self._route_change_proxy)
            window.location.hash = f"{path}{query_string}"

            def reattach_handler():
                window.addEventListener("hashchange", self._route_change_proxy)

            timeout_proxy = create_proxy(reattach_handler)
            window.setTimeout(timeout_proxy, 0)
        else:  # History mode
            try:
                full_path = f"{self.base_path}{path}{query_string}"
                window.eval("history.pushState(null, '', '" + full_path.replace("'", "\\'") + "')")
            except Exception as e:
                console.error(f"History pushState error: {str(e)}")
                window.location.href = full_path

    def _get_route_by_name(self, name: str) -> Optional[Tuple[Pattern, Route]]:
        """Find a route by its name."""
        for pattern, route in self.routes.items():
            if route.name == name:
                return pattern, route
            for child_pattern, child_route in route.children.items():
                if child_route.name == name:
                    return child_pattern, child_route
        return None

    def _build_path_with_params(self, pattern: Pattern, params: Dict[str, str]) -> Optional[str]:
        """Build a path string from a pattern and parameters."""
        path_pattern = pattern.pattern[1:-1]  # Remove ^ and $

        for param_name, param_value in params.items():
            # We need to match the literal regex string (?P<name>[^/]+) e.g. [^/]+
            param_regex = f"\\(\\?P<{param_name}>\\[\\^/\\]\\+\\)"
            if not re.search(param_regex, path_pattern):
                console.error(f"Parameter '{param_name}' not found in pattern '{path_pattern}'")
                return None

            path_pattern = re.sub(param_regex, str(param_value), path_pattern)

        if re.search(r"\(\?P<\w+>", path_pattern):
            console.error(f"Missing required parameters for path '{path_pattern}'")
            return None

        return path_pattern

    def _update_history(self, path: str, query_params: Optional[Dict[str, str]] = None) -> None:
        """Update the navigation history."""
        current_history = self.history_signal()
        current_index = self.current_history_index_signal()

        if current_index < len(current_history) - 1:
            while len(current_history) > current_index + 1:
                current_history.pop()

        current_history.append({"path": path, "query": query_params or {}})
        self.set_history(current_history)
        self.set_current_history_index(len(current_history) - 1)

    async def navigate(self, path: str, query_params: Optional[Dict[str, str]] = None,
                       add_to_history: bool = True) -> bool:
        """Navigate to a new route."""
        # Skip if already on this route (no actual route change)
        # if path == self.last_valid_route:
        #    return True 
        
        # Capture previous path for hooks
        prev_path = self.last_valid_route or "/"
        
        matched_routes_with_params, _ = self._find_matching_route(path.lstrip('/'), self.routes)
        if not matched_routes_with_params:
            console.warn(f"No route matched for navigation to: {path}")
            self._set_route_without_navigation(path)
            return False

        deepest_route, deepest_params = matched_routes_with_params[-1]

        can_access, redirect_path = await self._execute_hooks(self.before_hooks, path, deepest_params, query_params, matched_routes=matched_routes_with_params, stop_on_failure=True)

        if not can_access:
            resolved_path, resolved_query = self._resolve_redirect(redirect_path)
            if resolved_path:
                batch_updates(lambda: [
                    self._perform_redirect(resolved_path, resolved_query)
                ])
            return False

        self._cleanup_current()
       
        batch_updates(lambda: [
            self.set_params(deepest_params),
            self.set_query(query_params) if query_params else None,
            self.set_current_route({"path": path, "ts": time.time()})
        ])

        self.last_valid_route = path
        
        # Resolve prev_route_obj for hooks
        prev_matched, _ = self._find_matching_route(prev_path.lstrip('/'), self.routes)
        prev_route_obj = prev_matched[-1][0] if prev_matched else None

        # Execute after hooks
        asyncio.create_task(self._execute_hooks(self.after_hooks, path, deepest_params, matched_routes=matched_routes_with_params, stop_on_failure=False))

        query_string = ""
        if query_params:
            query_parts = [f"{key}={value}" for key, value in query_params.items()]
            if query_parts:
                query_string = f"?{'&'.join(query_parts)}"

        if add_to_history:
            self._update_history(path, query_params)

        if self.mode == self.HASH_MODE:
            window.location.hash = f"{path}{query_string}"
        else:  # History mode
            try:
                full_path = f"{self.base_path}{path}{query_string}"
                window.eval("history.pushState(null, '', '" + full_path.replace("'", "\\'") + "')")
            except Exception as e:
                console.error(f"History pushState error: {str(e)}")
                window.location.href = full_path

        return True

    async def go_back(self) -> bool:
        """Navigate back in history."""
        current_index = self.current_history_index_signal()
        history = self.history_signal()

        if current_index <= 0 or not history:
            console.warn("Cannot go back: No previous history entry")
            return False

        target_index = current_index - 1
        target_entry = history[target_index]

        success = await self.navigate(target_entry["path"], target_entry["query"], add_to_history=False)
        if success:
            self.set_current_history_index(target_index)

        return success

    async def go_forward(self) -> bool:
        """Navigate forward in history."""
        current_index = self.current_history_index_signal()
        history = self.history_signal()

        if current_index >= len(history) - 1 or not history:
            console.warn("Cannot go forward: No next history entry")
            return False

        target_index = current_index + 1
        target_entry = history[target_index]

        success = await self.navigate(target_entry["path"], target_entry["query"], add_to_history=False)
        if success:
            self.set_current_history_index(target_index)

        return success

    async def go_to(self, index: int) -> bool:
        """Navigate to a specific index in history."""
        history = self.history_signal()

        if index < 0 or index >= len(history) or not history:
            console.warn(f"Cannot go to index {index}: Invalid history index")
            return False

        target_entry = history[index]

        success = await self.navigate(target_entry["path"], target_entry["query"], add_to_history=False)
        if success:
            self.set_current_history_index(index)

        return success



    def before_routing(self, hook_fn: Callable) -> None:
        """Add a hook to run before routing. Returns True/None to allow, False to block, or str to redirect."""
        self.before_hooks.append(hook_fn)

    def after_routing(self, hook_fn: Callable) -> None:
        """Add a hook to run after routing completes."""
        self.after_hooks.append(hook_fn)

    def _cleanup_current(self) -> None:
        """Clean up the current route component and release resources."""
        self._current_component = None
        

    def _find_matching_route(self, path: str, routes: Dict[Pattern, Route],
                             base_path: str = "") -> Tuple[List[Tuple[Route, Dict[str, str]]], Optional[str]]:
        """Find all matching routes in the hierarchy, from parent to child."""
        matched_routes = []

        # First pass: Try to find exact matches only
        for regex, route in routes.items():
            match = regex.match(path)
            if match and match.group(0) == path:  # Exact match
                params = match.groupdict() if match.lastindex else {}
                matched_routes.append((route, params))

                # Check for empty child path
                if route.children:
                    for child_regex, child_route in route.children.items():
                        if child_regex.pattern == "^$":  # Empty path pattern
                            matched_routes.append((child_route, {}))
                            matched_routes.extend(self._find_empty_path_children(child_route))
                            return matched_routes, None

                return matched_routes, None

        # Second pass: Try to find parent routes with children that may contain our path
        for regex, route in routes.items():
            if not route.children:
                continue

            pattern_str = regex.pattern[1:-1]  # Remove ^ and $
            full_path = f"{base_path}{pattern_str}"

            # Try to match as a prefix
            match = re.search(regex.pattern[:-1], path)  # Partial match for routes with children

            if match:
                params = match.groupdict() if match.lastindex else {}
                consumed_path = match.group(0)
                remaining_path = path[len(consumed_path):] if consumed_path else path
                if remaining_path.startswith('/'):
                    remaining_path = remaining_path[1:]

                matched_routes.append((route, params))

                if not remaining_path:
                    for child_regex, child_route in route.children.items():
                        if child_regex.pattern == "^$":  # Empty path pattern
                            matched_routes.append((child_route, {}))
                            matched_routes.extend(self._find_empty_path_children(child_route))
                            return matched_routes, None

                child_routes, child_remaining = self._find_matching_route(
                    remaining_path, route.children, full_path + "/"
                )

                if child_routes:
                    matched_routes.extend(child_routes)
                    return matched_routes, child_remaining
                elif not remaining_path:
                    return matched_routes, None
                else:
                    matched_routes.pop()

        return [], path

    def _find_empty_path_children(self, route: Route) -> List[Tuple[Route, Dict[str, Any]]]:
        """Helper function to recursively find all empty path children of a route."""
        result = []

        if not route.children:
            return result

        for regex, child_route in route.children.items():
            if regex.pattern == "^$":  # Empty path pattern
                result.append((child_route, {}))
                result.extend(self._find_empty_path_children(child_route))

        return result

    # Modified section of the router.py file

    def route_outlet(self) -> Callable:
        """Create a rendering function for the current route hierarchy."""
        asyncio.create_task(self.intialize())

        @component()
        def Render(**props):
            current_route_state = track(lambda: self.current_route())
            # current_route_state is a dict {"path": "...", "ts": ...}
            # We track the whole object so any change (including just ts) triggers re-render
            path = current_route_state["path"]
            query_params = track(lambda: self.query_signal())

            if path is None:
                # Explicitly blocked or uninitialized to "nothing"
                return None
            
            # Fallback if path is empty string (not None), use last valid
            if not path:
                 path = self.last_valid_route or "/"

            def render_route_hierarchy(routes_with_params: List[Tuple[Route, Dict[str, str]]],
                                    remaining_path: str = None):
                if not routes_with_params:
                    return NotFound()

                try:
                    current_component = None
                    for route, route_params in reversed(routes_with_params):
                        Component = route.component

                        if not callable(Component):
                            raise TypeError(f"Route component for '{path}' is not callable")

                        if route.page_title and isinstance(route.page_title, str):
                            t.page_title(route.page_title)

                        props = {
                            "params": route_params,
                            "query": query_params,
                            "meta": {**route.meta},
                            "router": RouterDelegate(self),
                            "children": current_component
                        }

                        rendered_component = Component(**props)
                        current_component = rendered_component

                    return current_component
                except Exception as e:
                    console.error(f"Error rendering component: {str(e)}")
                    return ErrorView(path=path, error=e)

            matched_routes, remaining_path = self._find_matching_route(path.lstrip('/'), self.routes)

            if matched_routes and path is not None:
                return render_route_hierarchy(matched_routes, remaining_path)

            return NotFound()

        return Render

    def link(self, path: str, text: str, query_params: Optional[Dict[str, str]] = None,
             active_class: str = None, exact_match: bool = False):
        """Create a navigation link element with active link styling."""
        query_string = ""
        if query_params:
            query_parts = [f"{key}={value}" for key, value in query_params.items()]
            if query_parts:
                query_string = f"?{'&'.join(query_parts)}"

        if self.mode == self.HASH_MODE:
            href = f"#{path}{query_string}"
        else:  # History mode
            href = f"{self.base_path}{path}{query_string}"

        def handler(event):
            event.preventDefault()
            asyncio.create_task(self.navigate(path, query_params, True))

        onclick_proxy = create_proxy(handler)

        @component()
        def Link(**props):
            is_active = False

            current_route_state = self.current_route()
            current_path = current_route_state["path"] if isinstance(current_route_state, dict) else current_route_state

            if exact_match:
                is_active = current_path == path
            else:
                is_active = current_path.startswith(path)

            attributes = {"href": href, "onclick": onclick_proxy}
            if active_class and is_active:
                attributes["class_name"] = active_class
            
            return t.a(attributes, text)
        
        return Link


class RouterDelegate:
    _instance = None

    def __init__(self, router: Router):
        self._router = router
        RouterDelegate._instance = self

    @staticmethod
    def get_delegate():
        return RouterDelegate._instance

    def back(self):
        return asyncio.create_task(self._router.go_back())

    def forward(self):
        return asyncio.create_task(self._router.go_forward())

    def push(self, path: str, params: Optional[Dict[str, str]] = None):
        return asyncio.create_task(self._router.navigate(path, params, add_to_history=True))

    def go(self, path_or_index: str | int, params: Optional[Dict[str, str]] = None):
        if isinstance(path_or_index, int):
            return asyncio.create_task(self._router.go_to(path_or_index))

        route_match = self._router._get_route_by_name(path_or_index)

        if route_match:
            pattern, route = route_match
            path = self._router._build_path_with_params(pattern, params or {})

            if path:
                return asyncio.create_task(self._router.navigate(path, {}))
            else:
                console.error(f"Failed to build path for route '{path_or_index}'")
                return asyncio.create_task(asyncio.sleep(0))

        return asyncio.create_task(self._router.navigate(path_or_index, params or {}))

    def replace(self, path: str, params: Optional[Dict[str, str]] = None):
        return asyncio.create_task(self._router.navigate(path, params, add_to_history=False))

    def get_history(self) -> List[Dict[str, Any]]:
        return list(self._router.history_signal())

    def get_history_index(self) -> int:
        return self._router.current_history_index_signal()

    def can_go_back(self) -> bool:
        return self._router.current_history_index_signal() > 0

    def can_go_forward(self) -> bool:
        history = self._router.history_signal()
        current_index = self._router.current_history_index_signal()
        return current_index < len(history) - 1

    def get_current_route(self) -> str:
        return self._router.current_route()

    def get_current_params(self) -> Dict[str, str]:
        return self._router.params_signal()

    def get_current_query(self) -> Dict[str, str]:
        return self._router.query_signal()


@component()
def ErrorView(path: str, error: Exception, **props):
    styles = """
        .error {
            border: 1px solid #f74141;
            background-color: #ffdddd;
            color: #2d1919;
        }
    """
    import traceback
    traceback.print_exc()
    return t.div({}, [
        t.div({"class_name": "error"}, [
            t.h3({}, "Error"),
            t.p({}, f"Failed to render component for route '{path}': {str(error)}")
        ]),
    ], css=styles)

@component()
def NotFound(**props):
    return t.div({}, [t.h1({}, "404"), t.p({}, "Page not found")])


router_delegate = RouterDelegate.get_delegate