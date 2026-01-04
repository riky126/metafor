
import argparse
import os
import shutil
import sys
from .builder import build_project
from .server import run_server

def cmd_new(args):
    app_name = args.appname
    target_dir = os.path.join(os.getcwd(), app_name)
    
    if os.path.exists(target_dir):
        print(f"Error: Directory '{app_name}' already exists.")
        sys.exit(1)
        
    # Template dir is relative to this file
    cli_dir = os.path.dirname(os.path.abspath(__file__))
    template_dir = os.path.join(cli_dir, "templates", "starter_app")
    
    print(f"Creating new Metafor app '{app_name}'...")
    shutil.copytree(template_dir, target_dir)
    
    # Replace placeholders
    for filename in ["setup.py", "pyscript.toml", "manifest.json"]:
        file_path = os.path.join(target_dir, filename)
        if os.path.exists(file_path):
            with open(file_path, 'r') as f:
                content = f.read()
            
            # Replace placeholders
            # Template has "[app_name]" (with quotes), we replace [app_name] with app_name
            # Result: "[app_name]" -> "app_name" (valid JSON/TOML)
            # For Python: template has '[app_name]', we replace [app_name] with app_name
            # Result: '[app_name]' -> 'app_name' (valid Python)
            if filename == "setup.py":
                # Python: template has '[app_name]', replace with 'app_name'
                content = content.replace("[app_name]", app_name)
                content = content.replace("[app_description]", "A Metafor App")
                content = content.replace("[app_author]", "Author")
                content = content.replace("[app_author_email]", "email@example.com")
            else:
                # JSON/TOML: template has "[app_name]", replace [app_name] with app_name
                # This preserves the quotes: "[app_name]" -> "app_name"
                content = content.replace("[app_name]", app_name)
                content = content.replace("[app_description]", "A Metafor App")
                content = content.replace("[app_author]", "Author")
                content = content.replace("[app_author_email]", "email@example.com")
            
            with open(file_path, 'w') as f:
                f.write(content)
                
    print(f"App '{app_name}' created successfully!")
    print(f"cd {app_name}")
    print("metafor serve")

def cmd_build(args):
    build_project(os.getcwd(), output_type=args.output_type)

def cmd_serve(args):
    # First build
    build_project(os.getcwd(), output_type=args.output_type)
    run_server(args.host, args.port)

def cmd_clean(args):
    build_dir = os.path.join(os.getcwd(), "build")
    if os.path.exists(build_dir):
        print(f"Removing {build_dir}...")
        shutil.rmtree(build_dir)
        print("Clean complete.")
    else:
        print("Nothing to clean.")

def cmd_version(args):
    from . import __version__ as cli_version
    import metafor
    print(f"Metafor CLI version: {cli_version}")
    print(f"Metafor Framework version: {metafor.__version__}")

def cmd_test(args):
    import unittest
    start_dir = os.path.join(os.getcwd(), "tests")
    if not os.path.exists(start_dir):
        print(f"No tests directory found at {start_dir}")
        return
    
    print(f"Running tests in {start_dir}...")
    loader = unittest.TestLoader()
    suite = loader.discover(start_dir)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    if not result.wasSuccessful():
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="Metafor CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    # new command
    parser_new = subparsers.add_parser("new", help="Create a new Metafor app")
    parser_new.add_argument("appname", help="Name of the application")
    parser_new.set_defaults(func=cmd_new)
    
    # build command
    parser_build = subparsers.add_parser("build", help="Build the current app")
    parser_build.add_argument("--output-type", choices=['py', 'pyc'], default='pyc', help="Output type (py or pyc)")
    parser_build.set_defaults(func=cmd_build)
    
    # serve command
    parser_serve = subparsers.add_parser("serve", help="Serve the current app")
    parser_serve.add_argument("--port", type=int, default=8080, help="Port to serve on")
    parser_serve.add_argument("--host", default="", help="Host to serve on")
    parser_serve.add_argument("--output-type", choices=['py', 'pyc'], default='py', help="Output type (py or pyc)")
    parser_serve.set_defaults(func=cmd_serve)
    
    # clean command
    parser_clean = subparsers.add_parser("clean", help="Clean the build directory")
    parser_clean.set_defaults(func=cmd_clean)
    
    # version command
    parser_version = subparsers.add_parser("version", help="Show version information")
    parser_version.set_defaults(func=cmd_version)
    
    # test command
    parser_test = subparsers.add_parser("test", help="Run tests")
    parser_test.set_defaults(func=cmd_test)
    
    args = parser.parse_args()
    args.func(args)

if __name__ == "__main__":
    main()
