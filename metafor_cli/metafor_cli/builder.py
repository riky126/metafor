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

# Import bundler from the local package
from .bundler import MetaforBundler

def build_project(base_dir, output_type='pyc'):
    src_dir = base_dir
    out_dir = os.path.join(base_dir, "build")
    pyscript_toml = os.path.join(base_dir, "pyscript.toml")
    
    # Framework dir is the installed metafor package location
    # We can find it via the module
    import metafor
    framework_dir = os.path.dirname(os.path.abspath(metafor.__file__))
    
    use_pyc = (output_type == 'pyc')

    print(f"Building project in {base_dir}...")
    # print(f"Using framework from {framework_dir}")

    bundler = MetaforBundler(src_dir=src_dir, out_dir=out_dir, pyscript_toml=pyscript_toml, framework_dir=framework_dir, use_pyc=use_pyc)
    bundler.build()
    
    # print(f"Build complete.")
