import os
import sys
from unittest.mock import MagicMock

# Mock JS environment if not already mocked
# This is required because metafor package imports 'js' which exists only in Pyodide
if 'js' not in sys.modules:
    sys.modules['js'] = MagicMock()
if 'pyodide' not in sys.modules:
    sys.modules['pyodide'] = MagicMock()
if 'pyodide.ffi' not in sys.modules:
    sys.modules['pyodide.ffi'] = MagicMock()

# Development mode hack: Try to find metafor in parent directories
# This ensures we use the local metafor source if valid
current_dir = os.path.dirname(os.path.abspath(__file__))
# metafor_cli/metafor_cli/builder.py -> metafor_cli/metafor_cli -> metafor_cli -> root
project_root = os.path.dirname(os.path.dirname(current_dir))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Import bundler from the local package
from .bundler import MetaforBundler

def build_project(base_dir, output_type='pyc'):
    src_dir = base_dir
    out_dir = os.path.join(base_dir, "build")
    pyscript_toml = os.path.join(base_dir, "pyscript.toml")
    
    # Priority 1: Check relative to the app being built (dev repo use case)
    # This allows working with local framework changes without reinstalling metafor package
    framework_dir = None
    potential_framework = os.path.abspath(os.path.join(base_dir, "../metafor"))
    if os.path.exists(os.path.join(potential_framework, "__init__.py")):
         framework_dir = potential_framework
         print(f"Using framework from local path: {framework_dir}")

    # Priority 2: Use installed package
    if not framework_dir:
        try:
            import metafor
            framework_dir = os.path.dirname(metafor.__file__)
            print(f"Using framework from installed package: {framework_dir}")
        except ImportError as e:
            print(f"DEBUG: Could not import metafor: {e}")
            # Fallback to local development version in the root (for CLI dev)
            framework_dir = os.path.join(project_root, "metafor")
            print(f"Using fallback framework path: {framework_dir}")
    
    use_pyc = (output_type == 'pyc')

    print(f"Building project in {base_dir}...")
    # print(f"Using framework from {framework_dir}")

    bundler = MetaforBundler(src_dir=src_dir, out_dir=out_dir, pyscript_toml=pyscript_toml, framework_dir=framework_dir, use_pyc=use_pyc)
    bundler.build()
    
    # print(f"Build complete.")
