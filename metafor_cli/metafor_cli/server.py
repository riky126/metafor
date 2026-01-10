
import os
import sys
import threading
import time
from http import server
from .builder import build_project

def run_server(host, port):
    project_path = os.getcwd()
    
    # Start watcher in a separate thread
    WATCH_EXTENSIONS = {'.py', '.ptml', '.js', '.jsx', '.css', '.html', '.toml', '.scss', '.sass'}
    IGNORE_DIRS = {'build', '__pycache__', '.git', '.idea', '.vscode', 'node_modules'}
    WATCH_DIR = project_path
    
    # Global variable to track build time
    state = {'last_build_time': time.time()}
    # Condition to notify waiting clients
    build_condition = threading.Condition()

    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler

    # Watchdog Event Handler with Debouncing
    class DebouncedBuildHandler(FileSystemEventHandler):
        def __init__(self, callback, debounce_interval=0.1):
            self.callback = callback
            self.debounce_interval = debounce_interval
            self.timer = None
            
        def _trigger_build(self):
            if self.timer:
                self.timer.cancel()
            self.timer = threading.Timer(self.debounce_interval, self._execute_build)
            self.timer.start()
            
        def _execute_build(self):
            self.callback()
            
        def on_any_event(self, event):
            if event.is_directory:
                return

            # Strict Ignoring
            path = event.src_path
            # Check for ignored directories in path
            # We must explicitly ignore .egg-info here too, as it was the cause of the loop
            if any(part in path.split(os.sep) for part in IGNORE_DIRS) or '.egg-info' in path:
                return
            
            # Check for interesting extensions
            ext = os.path.splitext(path)[1]
            if ext in WATCH_EXTENSIONS:
                # Ignore .py files if they are derived from .ptml
                if ext == '.py':
                     ptml_path = os.path.splitext(path)[0] + '.ptml'
                     if os.path.exists(ptml_path):
                         return
                
                print(f"File changed: {os.path.relpath(path, WATCH_DIR)}")
                self._trigger_build()

    def run_build():
        print("Rebuilding...")
        try:
            build_project(WATCH_DIR, output_type='py')
            print("Build finished. Watching...")
            state['last_build_time'] = time.time()
            with build_condition:
                build_condition.notify_all()
        except Exception as e:
             print(f"\033[91mBuild failed: {e}\033[0m")

    def start_watcher():
        print(f"Watching {WATCH_DIR} for changes...")
        event_handler = DebouncedBuildHandler(run_build)
        observer = Observer()
        observer.schedule(event_handler, WATCH_DIR, recursive=True)
        observer.start()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            observer.stop()
        observer.join()

    watcher_thread = threading.Thread(target=start_watcher, daemon=True)
    watcher_thread.start()

    class Handler(server.SimpleHTTPRequestHandler):
        def do_GET(self):
            path = self.path.split("?")[0]
            
            if path == '/_metafor/events':
                self.send_response(200)
                self.send_header("Content-type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
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
    window.addEventListener('beforeunload', () => { console.log("Closing EventSource"); evtSource.close(); });
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

        def log_request(self, code='-', size='-'):
            if isinstance(code, int):
                if 200 <= code < 300:
                    code = f"\033[92m{code}\033[0m"
                elif 400 <= code < 500:
                    # Orange for Client Errors
                    code = f"\033[38;5;208m{code}\033[0m" 
                elif code >= 500:
                    # Red for Server Errors
                    code = f"\033[91m{code}\033[0m"
            self.log_message('"%s" %s', self.requestline, str(code))

        def log_message(self, format, *args):
            # Override to prevent sanitization of control characters which might happen in base class
            sys.stderr.write("%s - - [%s] %s\n" %
                            (self.client_address[0],
                             self.log_date_time_string(),
                             format % args))

        def end_headers(self):
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            super().end_headers()

    class ReusingThreadingHTTPServer(server.ThreadingHTTPServer):
        allow_reuse_address = True

    httpd = ReusingThreadingHTTPServer((host, port), Handler)
    display_host = host or 'localhost'
    print(f"\033[92mServing at http://{display_host}:{port}\033[0m")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n\033[38;5;208mShutdown signal received. Stopping server...\033[0m")
    finally:
        httpd.server_close()
        sys.exit(0)
