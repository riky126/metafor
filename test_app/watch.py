
import os
import time
import subprocess
import sys

WATCH_EXTENSIONS = {'.py', '.ptml', '.js', '.jsx', '.css', '.html', '.toml'}
IGNORE_DIRS = {'build', '__pycache__', '.git', '.idea', '.vscode', 'node_modules'}
BUILD_CMD = ["./build.sh"]

def get_file_mtimes(root_dir):
    mtimes = {}
    for root, dirs, files in os.walk(root_dir):
        # Filter ignored directories
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        
        for file in files:
            ext = os.path.splitext(file)[1]
            if ext in WATCH_EXTENSIONS:
                path = os.path.join(root, file)
                try:
                    mtimes[path] = os.path.getmtime(path)
                except OSError:
                    pass
    return mtimes

def main():
    root_dir = "."
    print(f"Watching {root_dir} for changes in {WATCH_EXTENSIONS}...")
    print(f"Ignoring: {IGNORE_DIRS}")
    
    last_mtimes = get_file_mtimes(root_dir)
    
    # Run build initially
    # print("Running initial build...")
    # subprocess.run(BUILD_CMD)
    
    try:
        while True:
            time.sleep(1)
            current_mtimes = get_file_mtimes(root_dir)
            
            changed = False
            added = []
            modified = []
            
            # Check for modified or added files
            for path, mtime in current_mtimes.items():
                if path not in last_mtimes:
                    added.append(path)
                    changed = True
                elif mtime > last_mtimes[path]:
                    modified.append(path)
                    changed = True
            
            # Check for deleted files (optional, but good for completeness)
            # deleted = [p for p in last_mtimes if p not in current_mtimes]
            # if deleted: changed = True
            
            if changed:
                print("\nChanges detected:")
                for p in added: print(f"  Added: {p}")
                for p in modified: print(f"  Modified: {p}")
                
                print("Running build...")
                subprocess.run(BUILD_CMD)
                print("Build finished. Watching...")
                
            last_mtimes = current_mtimes
            
    except KeyboardInterrupt:
        print("\nStopping watcher.")

if __name__ == "__main__":
    main()
