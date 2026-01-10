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
    
    def __init__(self, url: str):
        """
        Initialize a ServerPush connection.
        
        Args:
            url: The URL to connect to.
        """
        self.url = url
        
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
            self.close()
            
        try:
            self.set_state(ServerPushState.CONNECTING)
            console.log(f"ServerPush connecting to: {self.url}")
            self._es = EventSource.new(self.url)
            self.set_ready_state(self._es.readyState)
            
            self._setup_event_handlers()
            
        except Exception as e:
            self.set_state(ServerPushState.CLOSED)
            raise ChannelConnectionError(f"Failed to connect ServerPush: {e}") from e

    def _setup_event_handlers(self):
        if not self._es: return

        def on_open(event):
            self.set_state(ServerPushState.OPEN)
            self.set_ready_state(self._es.readyState)
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
            # EventSource attempts reconnect automatically, but we should notify.
            # State might flicker to CONNECTING.
            # self.set_state(ServerPushState.CONNECTING) # Maybe?
            
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

    def close(self):
        """Close the connection."""
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
