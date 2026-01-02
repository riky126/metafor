
import os
import sys
import threading
import time
from http import server
from .builder import build_project

def run_server(host, port):
    project_path = os.getcwd()
    
    # Start watcher in a separate thread
    WATCH_EXTENSIONS = {'.py', '.ptml', '.js', '.jsx', '.css', '.html', '.toml'}
    IGNORE_DIRS = {'build', '__pycache__', '.git', '.idea', '.vscode', 'node_modules'}
    WATCH_DIR = project_path
    
    # Global variable to track build time
    state = {'last_build_time': time.time()}
    # Condition to notify waiting clients
    build_condition = threading.Condition()

    def get_file_mtimes(root_dir):
        mtimes = {}
        for root, dirs, files in os.walk(root_dir):
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

    def run_watcher():
        print(f"Watching {WATCH_DIR} for changes...")
        last_mtimes = get_file_mtimes(WATCH_DIR)
        
        while True:
            time.sleep(1)
            current_mtimes = get_file_mtimes(WATCH_DIR)
            
            changed = False
            for path, mtime in current_mtimes.items():
                if path not in last_mtimes or mtime > last_mtimes[path]:
                    changed = True
                    break
            
            if changed:
                print("\nChanges detected. Rebuilding...")
                try:
                    build_project(WATCH_DIR, output_type='py')
                    print("Build finished. Watching...")
                    state['last_build_time'] = time.time()
                    
                    # Notify all waiting clients
                    with build_condition:
                        build_condition.notify_all()
                except Exception as e:
                    print(f"\033[91mBuild failed: {e}\033[0m")
                
                last_mtimes = current_mtimes

    watcher_thread = threading.Thread(target=run_watcher, daemon=True)
    watcher_thread.start()

    class Handler(server.SimpleHTTPRequestHandler):
        def do_GET(self):
            path = self.path.split("?")[0]
            
            if path == '/_metafor/events':
                self.send_response(200)
                self.send_header("Content-type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.end_headers()
                
                # Wait for build to finish
                with build_condition:
                    build_condition.wait()
                
                try:
                    self.wfile.write(b"data: reload\n\n")
                    self.wfile.flush()
                except BrokenPipeError:
                    pass
                return

            if not path.startswith("/metafor/"):
                self.path = f"/build{path}"
            
            # Intercept HTML files to inject reload script
            if self.path.endswith('.html') or self.path.endswith('/'):
                local_path = os.path.join(os.getcwd(), self.path.lstrip('/'))
                if os.path.isdir(local_path):
                    local_path = os.path.join(local_path, 'index.html')
                
                if os.path.exists(local_path) and local_path.endswith('.html'):
                    try:
                        with open(local_path, 'rb') as f:
                            content = f.read()
                        
                        # Inject script
                        script = b"""
<script>
(function() {
    const evtSource = new EventSource("/_metafor/events");
    evtSource.onmessage = function(event) {
        if (event.data === "reload") {
            console.log("Reload signal received, reloading...");
            window.location.reload();
        }
    };
    evtSource.onerror = function(err) {
        // EventSource errors are expected during development (connection interruptions)
        // These are harmless and don't affect the app functionality
    };
})();
</script>
</body>
"""
                        content = content.replace(b'</body>', script)
                        
                        self.send_response(200)
                        self.send_header("Content-type", "text/html")
                        self.send_header("Content-Length", str(len(content)))
                        self.end_headers()
                        self.wfile.write(content)
                        return
                    except Exception as e:
                        print(f"Error injecting script: {e}")

            return super().do_GET()

        def end_headers(self):
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            super().end_headers()

    class ReusingThreadingHTTPServer(server.ThreadingHTTPServer):
        allow_reuse_address = True

    httpd = ReusingThreadingHTTPServer((host, port), Handler)
    print(f"Serving at port {host or '*'}:{port}")
    httpd.serve_forever()
