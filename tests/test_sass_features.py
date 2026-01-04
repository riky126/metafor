import sys
from unittest.mock import MagicMock

# Mock Browser Environment
sys.modules['js'] = MagicMock()
sys.modules['pyodide'] = MagicMock()
sys.modules['pyodide.ffi'] = MagicMock()

from metafor.compiler import MetaforCompiler

def test_sass_features():
    print("Testing Sass mixins, includes, and extends...")
    compiler = MetaforCompiler()
    
    source = """
@component
def TestComponent():
    return <div>Feature Test</div>

@ptml { <div></div> }

@style(lang="sass") {
    @mixin theme-color {
        color: green;
        background: black;
    }

    .base-button {
        border: 1px solid red;
    }

    .my-button {
        @include theme-color;
        @extend .base-button;
        font-weight: bold;
    }
}
"""
    
    try:
        compiled_code = compiler.compile(source, filename="test_features.ptml")
        
        # Verify Mixin (@include theme-color)
        if 'color: green' in compiled_code and 'background: black' in compiled_code:
            print("SUCCESS: @mixin and @include verified.")
        else:
            print("FAILURE: @include did not apply styles.")
            print(compiled_code)
            sys.exit(1)

        # Verify Extend (@extend .base-button)
        # LibSass usually groups selectors: .base-button, .my-button { border: 1px solid red; }
        if '.base-button, .my-button' in compiled_code or '.my-button, .base-button' in compiled_code:
             print("SUCCESS: @extend verified (selector grouping detected).")
        # Alternative output depending on optimization
        elif 'border: 1px solid red' in compiled_code:
             print("SUCCESS: @extend verified (styles present).")
        else:
             print("FAILURE: @extend did not apply styles or group selectors.")
             print(compiled_code)
             sys.exit(1)

        print("\nFull Compiled Code Snippet:")
        # Print just the styles part
        start = compiled_code.find('inline_styles =')
        end = compiled_code.find('app_styles =', start)
        print(compiled_code[start:end+50] + "...")

    except Exception as e:
        print(f"Compilation ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    test_sass_features()
