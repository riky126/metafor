import json
import asyncio
import inspect
from enum import Enum
from typing import Any, Optional, Callable, Dict, List, Union
from pyodide.ffi import create_proxy, JsProxy
from js import EventSource, console, JSON

from metafor.core import create_signal, Signal
from .exceptions import ChannelConnectionError, ChannelMessageError

# EventSource readyState constants
ES_CONNECTING = 0
ES_OPEN = 1
ES_CLOSED = 2

class ServerPushState(Enum):
    """EventSource connection states."""
    CONNECTING = "connecting"
    OPEN = "open"
    CLOSED = "closed"

class ServerPush:
    """
    A persistent connection using Server-Sent Events (EventSource).
    Provides a Pythonic API for receiving server-pushed updates.
    """
    
    def __init__(self, url: str, max_retries: int = -1, base_delay: float = 1.0, max_delay: float = 30.0):
        """
        Initialize a ServerPush connection.
        
        Args:
            url: The URL to connect to.
            max_retries: Max retry attempts (-1 for infinite).
            base_delay: Initial retry delay in seconds.
            max_delay: Maximum retry delay in seconds.
        """
        self.url = url
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        
        self._retry_count = 0
        self._retry_task = None
        
        # Reactive state signals
        self.state_signal, self.set_state = create_signal(ServerPushState.CLOSED)
        self.ready_state_signal, self.set_ready_state = create_signal(2) # Default closed? ES uses 0,1,2
        
        # EventSource instance
        self._es: Optional[JsProxy] = None
        
        # Handlers
        self._on_open_handlers: List[Callable] = []
        self._on_message_handlers: List[Callable] = []
        self._on_error_handlers: List[Callable] = []
        
        # JS Handlers
        self._js_handlers = {}

    @property
    def state(self) -> ServerPushState:
        return self.state_signal()

    def _create_js_proxy(self, handler: Callable) -> JsProxy:
        return create_proxy(handler)

    def connect(self):
        """
        Establish the EventSource connection.
        Unlike WebSocket, this is synchronous in JS but we can wrap valid logic here.
        """
        if self._es and self._es.readyState == ES_OPEN:
            return

        if self._es:
            self.close(reset_retries=False)
            
        try:
            self.set_state(ServerPushState.CONNECTING)
            console.log(f"ServerPush connecting to: {self.url}")
            self._es = EventSource.new(self.url)
            self.set_ready_state(self._es.readyState)
            
            self._setup_event_handlers()
            
        except Exception as e:
            self.set_state(ServerPushState.CLOSED)
            # If immediate failure, schedule retry
            self._schedule_reconnect()
            # raise ChannelConnectionError(f"Failed to connect ServerPush: {e}") from e

    def _schedule_reconnect(self):
        if self.state == ServerPushState.OPEN: return
        if self.max_retries != -1 and self._retry_count >= self.max_retries:
            console.error(f"ServerPush: Max retries ({self.max_retries}) reached. Giving up.")
            return

        # Calculate delay (Exponential backoff with jitter?)
        # Simple for now: base * 2^retries
        delay = min(self.base_delay * (2 ** self._retry_count), self.max_delay)
        
        console.log(f"ServerPush: Reconnecting in {delay}s (Attempt {self._retry_count + 1})")
        
        async def _reconnect_task():
            await asyncio.sleep(delay)
            self._retry_count += 1
            try:
                self.connect()
            except Exception as e:
                console.error(f"Reconnect attempt failed: {e}")
                # Recursion handles next retry if connect() fails and calls schedule_reconnect
        
        if self._retry_task:
            self._retry_task.cancel()
        
        # We need a proper loop to schedule this on
        try:
             loop = asyncio.get_event_loop()
             if loop.is_running():
                 self._retry_task = loop.create_task(_reconnect_task())
             else:
                 # Fallback? usually strictly async env
                 pass
        except:
             pass

    def _setup_event_handlers(self):
        if not self._es: return

        def on_open(event):
            self.set_state(ServerPushState.OPEN)
            self.set_ready_state(self._es.readyState)
            
            # Reset retries on success
            self._retry_count = 0
            
            for handler in self._on_open_handlers:
                try: 
                    handler(event)
                except Exception as e:
                    console.error(f"Error in on_open handler: {e}")

        def on_message(event):
            try:
                # console.log("ServerPush Message:", event.data)
                # Parse JSON automatically if possible
                message = event.data
                try:
                    # Note: Using js.JSON.parse might be needed for complex objects, 
                    # but python json.loads is usually fine for strings.
                    # However, to maintain symmetry with Channel if it does fancier stuff:
                    # We'll just stick to string unless user parses.
                    # Actually, let's auto-parse like Channel often does or at least provide raw.
                    # For SSE, it's almost always JSON string.
                    if message:
                         pass # It's just a string, listeners handle parsing
                except:
                    pass
                
                for handler in self._on_message_handlers:
                    try:
                        res = handler(event) # Pass the full event or just data? Usually event.
                        if inspect.iscoroutine(res):
                            loop = asyncio.get_event_loop()
                            if loop.is_running():
                                loop.create_task(res)
                            else:
                                asyncio.create_task(res)
                    except Exception as e:
                        console.error(f"Error in on_message handler: {e}")

            except Exception as e:
                console.error(f"Error processing ServerPush message: {e}")

        def on_error(event):
            # EventSource attempts reconnect automatically for some errors (network), 
            # but usually NOT for 4xx/5xx or CORS, which close it immediately.
            
            # Check state
            ready_state = self._es.readyState
            self.set_ready_state(ready_state)
            
            if ready_state == ES_CLOSED:
                self.set_state(ServerPushState.CLOSED)
                console.warn(f"ServerPush Error (CLOSED): Scheduling reconnect...")
                self._schedule_reconnect()
            elif ready_state == ES_CONNECTING:
                self.set_state(ServerPushState.CONNECTING)
                # Browser is handling retry, but we might want to count it?
                # For now let browser handle the short-term retries
            
            for handler in self._on_error_handlers:
                try:
                    handler(event)
                except Exception as e:
                    console.error(f"Error in on_error handler: {e}")

        self._js_handlers = {
            'open': self._create_js_proxy(on_open),
            'message': self._create_js_proxy(on_message),
            'error': self._create_js_proxy(on_error)
        }

        self._es.addEventListener('open', self._js_handlers['open'])
        self._es.addEventListener('message', self._js_handlers['message'])
        self._es.addEventListener('error', self._js_handlers['error'])

    def close(self, reset_retries: bool = True):
        """Close the connection."""
        # Cancel pending retry
        if self._retry_task:
            self._retry_task.cancel()
            self._retry_task = None
            
        if reset_retries:
            self._retry_count = 0
            
        if not self._es: return
        
        self.set_state(ServerPushState.CLOSED)
        self._es.close()
        
        # Cleanup
        for event_type, handler in self._js_handlers.items():
            try:
                self._es.removeEventListener(event_type, handler)
            except: pass
        self._js_handlers.clear()
        self._es = None

    def on_open(self, handler: Callable) -> Callable:
        self._on_open_handlers.append(handler)
        return handler

    def on_message(self, handler: Callable) -> Callable:
        self._on_message_handlers.append(handler)
        return handler

    def on_error(self, handler: Callable) -> Callable:
        self._on_error_handlers.append(handler)
        return handler
