import unittest
import sys
from unittest.mock import MagicMock

# Mock browser-specific modules
sys.modules['js'] = MagicMock()
sys.modules['pyodide'] = MagicMock()
sys.modules['pyodide.ffi'] = MagicMock()

import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../metafor_cli')))

from metafor.compiler.compiler import MetaforCompiler

class TestNestedContext(unittest.TestCase):
    def test_nested_context_generation(self):
        compiler = MetaforCompiler()
        ptml_source = """
@component("App") @props {} <-- @context(ThemeContext) @MyApp {
    @value theme = "light"
} <-- @context(DBContext) @self {
    @value data = None
}

@ptml { <div></div> }
"""
        compiled_code = compiler.compile(ptml_source)
        
        print(compiled_code)
        
        # Check for nested structure
        # MyApp = ContextProvider(ThemeContext, "light", ContextProvider(DBContext, None, App))
        expected_line = 'MyApp = ContextProvider(ThemeContext, "light", ContextProvider(DBContext, None, App))'
        self.assertIn(expected_line, compiled_code)

if __name__ == '__main__':
    unittest.main()
