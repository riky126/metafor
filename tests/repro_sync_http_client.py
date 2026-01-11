
import sys
from unittest.mock import MagicMock

# Mock js module BEFORE imports
if "js" not in sys.modules:
    js = MagicMock()
    js.console = MagicMock()
    js.navigator = MagicMock()
    js.navigator.onLine = True
    js.window = MagicMock()
    js.window.addEventListener = MagicMock()
    js.window.Headers.new = MagicMock(return_value=MagicMock())
    sys.modules["js"] = js

if "pyodide" not in sys.modules:
    pyodide = MagicMock()
    pyodide.ffi = MagicMock()
    pyodide.ffi.create_proxy = MagicMock(side_effect=lambda x: x)
    pyodide.ffi.to_js = MagicMock(side_effect=lambda x, **kwargs: x)
    sys.modules["pyodide"] = pyodide
    sys.modules["pyodide.ffi"] = pyodide.ffi

import asyncio
from metafor.indexie.indexie import Indexie
from metafor.indexie.sync import SyncManager

# Mock Http Client
class MockHttpClient:
    def __init__(self):
        self.get_calls = []
        self.post_calls = []

    async def get(self, url, params=None, headers=None):
        self.get_calls.append({"url": url, "params": params, "headers": headers})
        print(f"MockHttpClient.get called with {url}")
        
        # Helper to fake JsProxy behavior
        def make_js_proxy(d):
            proxy = MagicMock()
            proxy.to_py.return_value = d
            # Ensure calling .get() raises AttributeError, simulating JsProxy
            del proxy.get 
            return {"status": 200, "data": proxy}

        # Simulate check_connection response
        if "ping=" in url:
            return {"status": 200, "data": {}}
            
        # Simulate pull response
        if "/pull" in url:
            data_dict = {
                "documents": [{"table": "users", "key": "1", "value": {"name": "Test User"}, "_rev": "1-abc"}],
                "checkpoint": "chk-1"
            }
            return make_js_proxy(data_dict)
            
        return {"status": 404, "data": {}}

    async def post(self, url, data=None, headers=None):
        self.post_calls.append({"url": url, "data": data, "headers": headers})
        print(f"MockHttpClient.post called with {url}, data={data}")
        
        def make_js_proxy(d):
            proxy = MagicMock()
            proxy.to_py.return_value = d
            del proxy.get
            return {"status": 200, "data": proxy}

        # Simulate push response
        if "/push" in url:
            data_dict = {
                "sync_receipts": [{"key": m["id"]} for m in data["mutations"]]
            }
            return make_js_proxy(data_dict)
            
        return {"status": 500, "data": {}}

async def test_sync_with_http_client():
    # 1. Setup
    http_client = MockHttpClient()
    db = Indexie("TestDB")
    
    # Setup SyncManager directly to avoid full DB init requiring browser globals
    sm = SyncManager(
        db, 
        "http://localhost:8000/sync", 
        http_client=http_client,
        pull_enabled=True
    )
    
    # 2. Test Check Connection
    print("\n--- Testing check_connection ---")
    reachable = await sm.check_connection()
    assert reachable is True
    assert len(http_client.get_calls) > 0
    assert "ping=" in http_client.get_calls[-1]["url"]
    print("check_connection passed")
    
    # 3. Test Pull
    print("\n--- Testing _pull ---")
    await sm._pull()
    assert any("/pull" in call["url"] for call in http_client.get_calls)
    print("_pull passed (triggered http_client.get)")

    # 4. Test Push
    print("\n--- Testing _push ---")
    # Mock queue response for push
    sm.queue = MagicMock()
    async def mock_peek(n):
        return [{
            "id": "mut-1", "table": "users", "op": "put", "value": {"name": "New User"}, "timestamp": 123456789
        }]
    sm.queue.peek = mock_peek
    
    async def mock_remove(ids):
        pass
    sm.queue.remove = mock_remove
    
    await sm._push()
    assert len(http_client.post_calls) > 0
    assert "/push" in http_client.post_calls[-1]["url"]
    print("_push passed (triggered http_client.post)")

    print("\nALL SCENARIOS PASSED")

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    loop.run_until_complete(test_sync_with_http_client())
