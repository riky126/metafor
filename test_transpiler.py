import sys
import os
from unittest.mock import MagicMock

# Mock js module for local testing
sys.modules['js'] = MagicMock()
sys.modules['pyodide'] = MagicMock()
sys.modules['pyodide.ffi'] = MagicMock()

# Add the project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from metafor.transpiler import jsx_to_dom_func

def test_transpiler():
    print("--- Testing counter.jsx ---")
    counter_jsx_path = os.path.abspath(os.path.join(os.path.dirname(__file__), 'app/jsx/counter.jsx'))
    try:
        output = jsx_to_dom_func(counter_jsx_path)
        print("Output Code:")
        print(output)
    except Exception as e:
        print(f"Error transpiling counter.jsx: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_transpiler()
