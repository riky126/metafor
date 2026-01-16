import os
import sys
import threading
import time
import hashlib
import base64
import struct
import select
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

    class WebSocketHandler:
        """Mixin for WebSocket Support (RFC 6455)"""
        
        def handshake(self):
            key = self.headers.get('Sec-WebSocket-Key')
            if not key:
                return False
            
            # Compute Accept
            # 1. Append Magic GUID
            # 2. SHA1
            # 3. Base64
            GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
            accept = base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()
            
            self.send_response(101)
            self.send_header("Upgrade", "websocket")
            self.send_header("Connection", "Upgrade")
            self.send_header("Sec-WebSocket-Accept", accept)
            self.end_headers()
            return True

        def send_frame(self, data, opcode=0x1):
            """Send a WebSocket frame."""
            # FIN=1, Opcode=text(1) or close(8)
            header = bytearray()
            b1 = 0x80 | (opcode & 0x0F)
            header.append(b1)
            
            payload = data.encode('utf-8') if isinstance(data, str) else data
            length = len(payload)
            
            if length <= 125:
                header.append(length)
            elif length <= 65535:
                header.append(126)
                header.extend(struct.pack("!H", length))
            else:
                header.append(127)
                header.extend(struct.pack("!Q", length))
                
            try:
                self.wfile.write(header + payload)
                self.wfile.flush()
            except BrokenPipeError:
                pass

        def read_frame(self):
            """Read a WebSocket frame (blocking)."""
            # Implementation omitted for simplicity as we only push updates
            # But we must read to detect close
            pass

    class Handler(server.SimpleHTTPRequestHandler, WebSocketHandler):
        def do_GET(self):
            path = self.path.split("?")[0]
            
            # WebSocket Upgrade
            if self.headers.get("Upgrade") == "websocket" and path == "/_metafor/ws":
                if self.handshake():
                    self.handle_websocket()
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
    let ws;
    
    function connect() {
        // Use ws:// or wss:// depending on current protocol
        const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
        const url = `${proto}://${window.location.host}/_metafor/ws`;
        
        ws = new WebSocket(url);
        
        ws.onopen = function() {
            console.log("[Metafor] Hot Module Reload Connected.");
        };
        
        ws.onmessage = function(event) {
            if (event.data === "reload") {
                window.location.reload();
            }
        };
        
        ws.onclose = function() {
            console.warn("[Metafor] Connection lost. Retrying in 1s...");
            setTimeout(connect, 1000);
        };
        
        ws.ononerror = function(err) {
            ws.close();
        };
    }
    
    connect();
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
            
        def handle_websocket(self):
            """Handle the WebSocket connection loop."""
            # Register for build notifications
            try:
                # We need a way to break out of wait() if socket closes
                # Standard waiting with timeout loop
                while True:
                    # Use select to check if client disconnected
                    r, _, _ = select.select([self.connection], [], [], 0.05)
                    if r:
                        # Client sent something (likely close frame or ping), simple read to clear/detect close
                        try:
                            data = self.connection.recv(1024)
                            if not data: break # Closed
                        except:
                            break # Error
                    
                    # Check for build
                    acquired = build_condition.acquire(timeout=0.1)
                    if acquired:
                        # Wait for notify
                        triggered = build_condition.wait(timeout=0.5) 
                        build_condition.release()
                        
                        if triggered:
                            self.send_frame("reload")
                        
            except (ConnectionResetError, BrokenPipeError):
                pass
            finally:
                pass


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
