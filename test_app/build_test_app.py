import sys
from unittest.mock import MagicMock

# Mock JS environment
sys.modules['js'] = MagicMock()
sys.modules['pyodide'] = MagicMock()
sys.modules['pyodide.ffi'] = MagicMock()

import os
# Add root to path to find metafor
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from metafor.bundler import MetaforBundler

def main():
    # Build test_app
    base_dir = os.path.dirname(os.path.abspath(__file__))
    src_dir = base_dir
    out_dir = os.path.join(base_dir, "build")
    pyscript_toml = os.path.join(base_dir, "pyscript.toml")
    framework_dir = os.path.join(base_dir, "../metafor")
    
    import argparse
    parser = argparse.ArgumentParser(description='Build the test app.')
    parser.add_argument('--output-type', choices=['py', 'pyc'], default='pyc', help='Output type for Python files (py or pyc)')
    args = parser.parse_args()

    use_pyc = (args.output_type == 'pyc')

    bundler = MetaforBundler(src_dir=src_dir, out_dir=out_dir, pyscript_toml=pyscript_toml, framework_dir=framework_dir, use_pyc=use_pyc)
    bundler.build()
    
    print(f"Test App Build complete (Output: {args.output_type}).")

if __name__ == "__main__":
    main()
