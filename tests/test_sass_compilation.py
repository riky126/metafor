import sys
from unittest.mock import MagicMock

# Mock Browser Environment for local testing
sys.modules['js'] = MagicMock()
sys.modules['pyodide'] = MagicMock()
sys.modules['pyodide.ffi'] = MagicMock()

from metafor.compiler import MetaforCompiler

def test_inline_sass():
    print("Testing inline Sass compilation...")
    compiler = MetaforCompiler()
    
    source = """
@component
def TestComponent():
    return <div>Hello</div>

@ptml {
    <div>Content</div>
}


@style(lang="sass") {
    $primary: #ff0000;
    
    .container {
        color: $primary;
        
        &:hover {
            color: blue;
        }
    }
}
"""
    
    try:
        compiled_code = compiler.compile(source, filename="test.ptml")
        
        # Check if compiled CSS is present in the output
        if 'color: #ff0000' in compiled_code or 'color: red' in compiled_code:
            print("SUCCESS: Sass variable $primary compiled to color.")
        else:
            print("FAILURE: Could not find compiled color.")
            print("Compiled Code snippet:")
            print(compiled_code)
            sys.exit(1)
            
        if '.container:hover' in compiled_code:
             print("SUCCESS: Sass nesting compiled.")
        else:
             print("FAILURE: Could not find nested selector.")
             sys.exit(1)

        print("\nFull Compiled Code:")
        print(compiled_code)

    except Exception as e:
        print(f"Compilation ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    test_inline_sass()
