import unittest
import sys
from unittest.mock import MagicMock, AsyncMock

# Mock browser-specific modules
js_mock = MagicMock()
js_mock.window = MagicMock()
js_mock.console = MagicMock()
js_mock.document = MagicMock()
js_mock.setTimeout = MagicMock()
sys.modules['js'] = js_mock
sys.modules['pyodide'] = MagicMock()
sys.modules['pyodide.ffi'] = MagicMock()

import asyncio
import os
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../')))

from metafor.router import Router, Route
from metafor.core import create_signal

class TestRouterGuards(unittest.IsolatedAsyncioTestCase):
    async def test_guard_allow(self):
        def AdminComponent(**props): return "Admin"
        AdminComponent.__path__ = "/admin"
        
        routes = [Route(component=AdminComponent)]
        
        # Hook that allows access
        async def auth_hook(prev, curr, **params):
             if curr.path == "/admin":
                 return None # Allow
             return None
        
        router = Router(routes, initial_route="/")
        # Use new API
        router.before_routing(auth_hook)
        
        router._set_route_without_navigation("/")
        
        success = await router.navigate("/admin")
        self.assertTrue(success)
        self.assertEqual(router.current_route()["path"], "/admin")

    async def test_guard_deny(self):
        def AdminComponent(**props): return "Admin"
        AdminComponent.__path__ = "/admin"
        
        def LoginComponent(**props): return "Login"
        LoginComponent.__path__ = "/login"
        
        routes = [
            Route(component=AdminComponent),
            Route(component=LoginComponent)
        ]
        
        # Hook that denies access
        async def auth_hook(prev, curr, **params):
            if curr.path == "/admin":
                return "/login" # Redirect
            return None
            
        router = Router(routes, initial_route="/")
        router.before_routing(auth_hook)
        
        router._set_route_without_navigation("/")
        
        success = await router.navigate("/admin")
        self.assertFalse(success)
        # Should redirect to /login
        self.assertEqual(router.current_route()["path"], "/login")
        
    async def test_after_hook(self):
        def TestComponent(**props): return "Test"
        TestComponent.__path__ = "/test"
        
        routes = [Route(component=TestComponent)]
        
        router = Router(routes, initial_route="/")
        router._set_route_without_navigation("/")
        
        after_hook_called = False
        async def after_hook(prev, curr, **params):
            nonlocal after_hook_called
            if curr.path == "/test":
                after_hook_called = True
            
        router.after_routing(after_hook)
        
        success = await router.navigate("/test")
        self.assertTrue(success)
        
        # Allow async task to run
        await asyncio.sleep(0)
        
        self.assertTrue(after_hook_called)

    async def test_guard_path_params_resolution(self):
        def UserComponent(**props): return "User"
        UserComponent.__path__ = "/users/:id"
        
        routes = [Route(component=UserComponent)]
        
        captured_to_path = None
        
        async def check_path_guard(prev, curr, **params):
            nonlocal captured_to_path
            captured_to_path = curr.path
            return None
            
        router = Router(routes, initial_route="/")
        router.before_routing(check_path_guard)
        
        router._set_route_without_navigation("/")
        
        # Navigate to a path with params
        await router.navigate("/users/123")
        
        # The path in the route object passed to guard should be resolved (/users/123)
        # NOT the pattern (/users/:id)
        self.assertEqual(captured_to_path, "/users/123")

    async def test_guard_dict_redirect(self):
        def AdminComponent(**props): return "Admin"
        AdminComponent.__path__ = "/admin"
        
        def UserComponent(**props): return "User"
        UserComponent.__path__ = "/users/:id"
        
        routes = [
            Route(component=AdminComponent),
            Route(component=UserComponent)
        ]
        
        # Hook that redirects using dict with params
        async def auth_hook(prev, curr, **params):
            if curr.path == "/admin":
                return {"path": "/users/:id", "params": {"id": "999"}}
            return None
            
        router = Router(routes, initial_route="/")
        router.before_routing(auth_hook)
        
        router._set_route_without_navigation("/")
        
        success = await router.navigate("/admin")
        self.assertFalse(success)
        # Should redirect to /users/999
        self.assertEqual(router.current_route()["path"], "/users/999")

    async def test_guard_query_redirect(self):
        def SearchComponent(**props): return "Search"
        SearchComponent.__path__ = "/search"
        
        def HomeComponent(**props): return "Home"
        HomeComponent.__path__ = "/"

        routes = [Route(component=SearchComponent), Route(component=HomeComponent)]
        
        # Hook that redirects with query
        async def query_hook(prev, curr, **params):
            if curr.path == "/": # Initial nav might be /
                return {"path": "/search", "query": {"q": "term"}}
            return None
            
        router = Router(routes, initial_route="/")
        router.before_routing(query_hook)
        
        router._set_route_without_navigation("/")
        
        # This navigate should trigger hook which redirects
        success = await router.navigate("/") 
        self.assertFalse(success)
        
        self.assertEqual(router.current_route()["path"], "/search")
        self.assertEqual(router.query_signal(), {"q": "term"})

    async def test_meta_propagation(self):
        def Parent1(**props): return "P1"
        Parent1.__path__ = "/p1"
        def Child1(**props): return "C1"
        Child1.__path__ = "/c1"

        # Case 1: Propagate True
        r1 = Route(Parent1, meta={"inherited": True}, propagate=True, children=[
            Route(Child1, meta={"own": 1})
        ])
        # Child is in r1.children. We need to find the compiled child route object
        # The key is regex, value is Route object.
        # But wait, children are compiled into dict.
        # Let's just check via Router or access internal
        child_route_1 = list(r1.children.values())[0]
        self.assertTrue(child_route_1.meta.get("inherited"))
        self.assertEqual(child_route_1.meta.get("own"), 1)

        def Parent2(**props): return "P2"
        Parent2.__path__ = "/p2"
        def Child2(**props): return "C2"
        Child2.__path__ = "/c2"

        # Case 2: Propagate False (Default)
        r2 = Route(Parent2, meta={"inherited": True}, children=[
            Route(Child2, meta={"own": 2})
        ])
        child_route_2 = list(r2.children.values())[0]
        self.assertIsNone(child_route_2.meta.get("inherited"))
        self.assertEqual(child_route_2.meta.get("own"), 2)

    async def test_hook_matched_routes(self):
        # Verify matched_routes passed to hook
        def Parent(**props): return "P"
        Parent.__path__ = "/parent"
        def Child(**props): return "C"
        Child.__path__ = "/child"
        
        # Propagation False, but want to check parent meta via matched_routes
        routes = [
            Route(Parent, meta={"auth": True}, propagate=False, children=[
                Route(Child)
            ])
        ]
        
        found_parent_auth = False
        
        async def check_parents(prev, curr, **kwargs):
            nonlocal found_parent_auth
            matched = kwargs.get("matched_routes", [])
            # Check if any route in chain has auth: True
            for r in matched:
                if r.meta.get("auth"):
                    found_parent_auth = True
            return None
            
        router = Router(routes, initial_route="/")
        router.before_routing(check_parents)
        router._set_route_without_navigation("/")
        
        await router.navigate("/parent/child")
        self.assertTrue(found_parent_auth)

    async def test_initial_blocking(self):
        # Test blocking on initial route
        def Protected(**props): return "Protected"
        Protected.__path__ = "/protected"
        
        routes = [Route(Protected)]
        
        router = Router(routes, initial_route="/protected")
        
        # Hook that blocks everything
        def block_all(prev, curr, **kwargs):
            return False
            
        router.before_routing(block_all)
        
        # Mock window location
        from js import window
        window.location.hash = "#/protected"

        # Simulate initial route change handling
        # Since Router init sets current_route optimistically, we rely on _handle_route_change
        # to correct it if blocked.
        await router._handle_route_change(None)
        
        # Should be blocked, so current route should be None
        current = router.current_route()
        self.assertIsNone(current["path"])

if __name__ == '__main__':
    unittest.main()
