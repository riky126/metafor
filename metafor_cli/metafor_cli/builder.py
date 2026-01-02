
import os
import sys
from unittest.mock import MagicMock

# Mock JS environment if not already mocked
if 'js' not in sys.modules:
    sys.modules['js'] = MagicMock()
if 'pyodide' not in sys.modules:
    sys.modules['pyodide'] = MagicMock()
if 'pyodide.ffi' not in sys.modules:
    sys.modules['pyodide.ffi'] = MagicMock()

# Import bundler from the metafor package
from metafor.bundler import MetaforBundler

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
    print(f"Using framework from {framework_dir}")

    bundler = MetaforBundler(src_dir=src_dir, out_dir=out_dir, pyscript_toml=pyscript_toml, framework_dir=framework_dir, use_pyc=use_pyc)
    bundler.build()
    
    print(f"Build complete.")
