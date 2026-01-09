import asyncio
import sys
import os
import json
import urllib.parse
from unittest.mock import MagicMock, patch

# Ensure we can import the package
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../')))

# --- MOCK ENVIRONMENT SETUP ---
if 'js' not in sys.modules:
    js_mock = MagicMock()
    # Log to stdout
    js_mock.console.log.side_effect = lambda *args: print(f"[MOCK JS] {args}")
    js_mock.console.error.side_effect = lambda *args: print(f"[MOCK JS ERROR] {args}")
    js_mock.JSON.parse = json.loads
    sys.modules['js'] = js_mock

if 'pyodide' not in sys.modules:
    sys.modules['pyodide'] = MagicMock()
if 'pyodide.ffi' not in sys.modules:
    pyodide_ffi_mock = MagicMock()
    pyodide_ffi_mock.create_proxy = MagicMock(side_effect=lambda x: x)
    sys.modules['pyodide.ffi'] = pyodide_ffi_mock

print("Environment mocked inline.")

from metafor.storage import Table

async def test_sse_json_string_parsing():
    print("\n[Test 1] Testing SSE JSON String Parsing Fix...")
    
    mock_http = MagicMock()
    
    async def async_get(*args, **kwargs):
        print(f"  > Http GET called params={kwargs.get('params')}")
        return {
            'status': 200,
            'data': [],
            'headers': {"Electric-Offset": "12345", "Electric-Handle": "test-handle"}
        }
    mock_http.get = async_get

    table = Table("users", "id", {}, "db_name")
    
    with patch('metafor.storage.ServerPush') as MockServerPush:
        mock_push_instance = MockServerPush.return_value
        
        captured_handler = None
        def on_message_side_effect(handler):
            nonlocal captured_handler
            captured_handler = handler
        mock_push_instance.on_message.side_effect = on_message_side_effect
        
        await table.sync_electric(
            url="http://localhost:8080", 
            http_client=mock_http, 
            params={"live": "true"}
        )
        
        if not captured_handler:
            print("❌ FAILED: on_message handler was not registered!")
            return

        # Test Payload
        test_payload = '[{"key": "value", "op": "INSERT"}]'
        mock_event = MagicMock()
        mock_event.data = test_payload
        
        await captured_handler(mock_event)
        
        # Verify result log
        from js import console
        success = False
        for call in console.log.call_args_list:
             msg = str(call[0][0])
             if "Live Update Data Received" in msg and "[{'key': 'value', 'op': 'INSERT'}]" in msg:
                 success = True
                 break
        
        if success:
             print("✅ TEST PASSED: JSON string parsed correctly.")
        else:
             print("❌ TEST FAILED: Parsed data log not found.")

async def test_sync_electric_integration():
    print("\n[Test 2] Testing sync_electric custom integration params...")
    
    # User requested test:
    # await db.users.sync_electric(
    #     url="http://localhost:8000/stream/electric",
    #     params={"table": "users"},
    #     http_client=http_client
    # )
    
    mock_http = MagicMock()
    mock_offset = "offset_999"
    mock_handle = "handle_ABC"
    
    async def async_get(url, params=None, headers=None):
        print(f"  > Http GET called url={url} params={params}")
        # Validate inputs
        if "table" not in params or params["table"] != "users":
            print("❌ FAILED: 'table' param missing or incorrect in Snapshot request")
        
        return {
            'status': 200,
            'data': [],
            'headers': {
                "Electric-Offset": mock_offset, 
                "Electric-Handle": mock_handle
            }
        }
    mock_http.get = async_get

    table = Table("users", "id", {}, "db_name")

    with patch('metafor.storage.ServerPush') as MockServerPush:
        mock_push_instance = MockServerPush.return_value

        # Capture handler
        captured_handler = None
        def on_message_side_effect(handler):
            nonlocal captured_handler
            captured_handler = handler
        mock_push_instance.on_message.side_effect = on_message_side_effect

        # Run SUT
        await table.sync_electric(
            url="http://localhost:8000/stream/electric",
            params={"table": "users"},
            http_client=mock_http
        )
        
        # Verify ServerPush URL
        if not MockServerPush.called:
             print("❌ FAILED: ServerPush not initialized")
             return
             
        init_args = MockServerPush.call_args[0]
        sse_url = init_args[0]
        print(f"  > ServerPush initialized with URL: {sse_url}")
        
        parsed = urllib.parse.urlparse(sse_url)
        qs = urllib.parse.parse_qs(parsed.query)
        
        # Validation
        errors = []
        if qs.get('live') != ['true']: errors.append("Missing live=true")
        if qs.get('table') != ['users']: errors.append("Missing/Wrong table param")
        if qs.get('offset') != [mock_offset]: errors.append(f"Wrong offset: {qs.get('offset')}")
        if qs.get('handle') != [mock_handle]: errors.append(f"Wrong handle: {qs.get('handle')}")
        
        if errors:
            print(f"❌ TEST FAILED URL Params: {errors}")
            return

        print("  ✓ URL and Headers propagated correctly.")

        # Verify on_message execution
        if not captured_handler:
             print("❌ FAILED: on_message handler was not registered!")
             return

        print("  > Handler registered. Simulating event...")
        test_payload = '[{"key": "integ_test", "value": "works"}]'
        mock_event = MagicMock()
        mock_event.data = test_payload
        
        await captured_handler(mock_event)

        # Verify logs
        from js import console
        success = False
        for call in console.log.call_args_list:
             msg = str(call[0][0])
             if "integ_test" in msg and "works" in msg:
                 success = True
                 break
        
        if success:
             print("✅ TEST PASSED: on_message handler processed the event.")
        else:
             print("❌ TEST FAILED: Event data not found in logs.")

async def run_tests():
    try:
        await test_sse_json_string_parsing()
        await test_sync_electric_integration()
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(run_tests())
