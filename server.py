import argparse
import os
import pathlib
import sys
import threading
import time
import subprocess
from http import server

project_path = pathlib.Path(__file__).parent
metafor_path = project_path / "metafor"
examples_path = project_path / "test_app/build"

assert project_path.is_dir()
assert metafor_path.is_dir()
assert (metafor_path / "core.py").exists()

sys.path.append(str(project_path))


class Handler(server.SimpleHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?")[0]

        # We want to serve the examples from the /examples directory, but also allow pulls from /puepy/ for live
        # changes to code. This basically just treats /examples as the content root, unless the path starts with /puepy/
        if not path.startswith("/metafor/"):
            self.path = f"/test_app/build{path}"

        return super().do_GET()

    def end_headers(self):
        """
        Cache nothing!
        """
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="A simple HTTP server to serve examples of PuePy")
    parser.add_argument("--host", default="", help="The host on which the server runs")
    parser.add_argument("--port", type=int, default=8080, help="The port on which the server listens")
    args = parser.parse_args()

    os.chdir(project_path)
    
    # Start watcher in a separate thread
    WATCH_EXTENSIONS = {'.py', '.ptml', '.js', '.jsx', '.css', '.html', '.toml'}
    IGNORE_DIRS = {'build', '__pycache__', '.git', '.idea', '.vscode', 'node_modules'}
    # Build command relative to project root
    BUILD_CMD = ["./test_app/build.sh"]
    WATCH_DIR = project_path / "test_app"
    
    # Global variable to track build time
    last_build_time = time.time()
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
        global last_build_time
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
                # Run build command from test_app directory to match original behavior
                subprocess.run(["./build.sh"], cwd=WATCH_DIR)
                print("Build finished. Watching...")
                last_build_time = time.time()
                last_mtimes = current_mtimes
                
                # Notify all waiting clients
                with build_condition:
                    build_condition.notify_all()

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

            # We want to serve the examples from the /examples directory, but also allow pulls from /puepy/ for live
            # changes to code. This basically just treats /examples as the content root, unless the path starts with /puepy/
            if not path.startswith("/metafor/"):
                self.path = f"/test_app/build{path}"
            
            # Intercept HTML files to inject reload script
            if self.path.endswith('.html') or self.path.endswith('/'):
                # Resolve the actual file path
                # SimpleHTTPRequestHandler uses translate_path but it's complex to replicate exactly.
                # However, we modified self.path above, so we can try to find it.
                # But wait, super().do_GET() does the serving.
                # If we want to inject, we must serve it ourselves.
                
                # Let's use a simpler approach: read the file if it exists and serve it.
                # We need to handle the CWD change done in main()
                
                # Re-construct the local path based on how SimpleHTTPRequestHandler would do it (roughly)
                # We are in project_path.
                # self.path starts with /
                
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
        console.log("EventSource failed:", err);
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
                        # Fallback to default serving

            return super().do_GET()

        def end_headers(self):
            """
            Cache nothing!
            """
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            super().end_headers()

    class ReusingThreadingHTTPServer(server.ThreadingHTTPServer):
        allow_reuse_address = True

    httpd = ReusingThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Serving at port {args.host or '*'}:{args.port}")
    httpd.serve_forever()


