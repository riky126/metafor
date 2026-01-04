
import sys
from unittest.mock import MagicMock, patch

# Mock js and pyodide modules before importing metafor
sys.modules["js"] = MagicMock()
sys.modules["pyodide"] = MagicMock()
sys.modules["pyodide.ffi"] = MagicMock()

import asyncio
import unittest
from metafor.http.client import Http

class TestHttpMethods(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Patch to_js to return the input so we can inspect it
        self.to_js_patcher = patch('metafor.http.client.to_js', side_effect=lambda x: x)
        self.to_js_patcher.start()

    async def asyncTearDown(self):
        self.to_js_patcher.stop()

    async def test_head_method(self):
        http = Http()
        with patch('metafor.http.client.fetch', new_callable=MagicMock) as mock_fetch:
            future = asyncio.Future()
            future.set_result(MagicMock(status=200, headers=MagicMock(get=lambda k,d: "")))
            mock_fetch.return_value = future
            
            await http.head("/test")
            
            args, kwargs = mock_fetch.call_args
            self.assertEqual(kwargs.get("method"), "HEAD")

    async def test_options_method(self):
        http = Http()
        with patch('metafor.http.client.fetch', new_callable=MagicMock) as mock_fetch:
            future = asyncio.Future()
            future.set_result(MagicMock(status=200, headers=MagicMock(get=lambda k,d: "")))
            mock_fetch.return_value = future
            
            await http.options("/test")
            
            args, kwargs = mock_fetch.call_args
            self.assertEqual(kwargs.get("method"), "OPTIONS")

if __name__ == '__main__':
    unittest.main()
