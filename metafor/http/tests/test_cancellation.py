
import sys
from unittest.mock import MagicMock, patch

# Mock js module
sys.modules["js"] = MagicMock()
# Mock AbortController
mock_abort_controller = MagicMock()
sys.modules["js"].AbortController = mock_abort_controller
sys.modules["pyodide"] = MagicMock()
sys.modules["pyodide.ffi"] = MagicMock()

import asyncio
import unittest
# Import after mocking
from metafor.http.client import Http
from metafor.http.support import CancellationToken

class TestHttpCancellation(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Patch to_js to return the input so we can inspect it
        self.to_js_patcher = patch('metafor.http.client.to_js', side_effect=lambda x: x)
        self.to_js_patcher.start()
        
        # Reset mocks
        mock_abort_controller.reset_mock()
        mock_abort_controller.new.return_value = MagicMock()

    async def asyncTearDown(self):
        self.to_js_patcher.stop()

    async def test_cancellation_token_init(self):
        token = CancellationToken()
        # Verify it created an AbortController
        mock_abort_controller.new.assert_called_once()

    async def test_request_with_cancellation(self):
        http = Http()
        token = CancellationToken()
        mock_signal = token.get_signal()
        
        with patch('metafor.http.client.fetch', new_callable=MagicMock) as mock_fetch:
            future = asyncio.Future()
            future.set_result(MagicMock(status=200, headers=MagicMock(get=lambda k,d: "")))
            mock_fetch.return_value = future
            
            await http.get("/test", cancellation_token=token)
            
            args, kwargs = mock_fetch.call_args
            # Verify signal was passed
            self.assertEqual(kwargs.get("signal"), mock_signal)

    async def test_token_cancel(self):
        token = CancellationToken()
        controller_instance = mock_abort_controller.new.return_value
        
        token.cancel()
        
        # Verify abort was called on the key instance
        controller_instance.abort.assert_called_once()
        self.assertTrue(token.is_cancelled)

if __name__ == '__main__':
    unittest.main()
