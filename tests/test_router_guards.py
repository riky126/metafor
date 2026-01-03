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
        
        # Guard that allows access
        async def auth_guard(prev, curr, **params):
            return True
            
        guards = {"/admin": (auth_guard, "/login")}
        
        router = Router(routes, initial_route="/", guards=guards)
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
        
        # Guard that denies access
        async def auth_guard(prev, curr, **params):
            return False
            
        guards = {"/admin": (auth_guard, "/login")}
        
        router = Router(routes, initial_route="/", guards=guards)
        router._set_route_without_navigation("/")
        
        success = await router.navigate("/admin")
        self.assertFalse(success)
        # Should redirect to /login
        self.assertEqual(router.current_route()["path"], "/login")

if __name__ == '__main__':
    unittest.main()
