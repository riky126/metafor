import json
import inspect
import asyncio
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
        
        # Reconnection tracking
        self._reconnect_count = 0
        self._last_reconnect_time = 0
        self._max_reconnects = 10  # Limit reconnection attempts
        self._reconnect_window = 5000  # 5 seconds window

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
            # Reset reconnect count on successful connection
            self._reconnect_count = 0
            console.log(f"ServerPush connection opened: {self.url}")
            for handler in self._on_open_handlers:
                try: 
                    result = handler(event)
                    # Handle async handlers
                    if inspect.iscoroutine(result):
                        asyncio.create_task(result)
                except Exception as e:
                    console.error(f"Error in on_open handler: {e}", exc_info=True)

        def on_message(event):
            try:
                message_data = getattr(event, 'data', None)
                message_type = getattr(event, 'type', 'message')
                console.log(f"ServerPush Message received (type={message_type}, data_length={len(message_data) if message_data else 0}): {message_data[:100] if message_data else 'None'}...")
                
                # Parse JSON automatically if possible
                message = message_data
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
                
                if not self._on_message_handlers:
                    console.warn("ServerPush: No message handlers registered!")
                
                for handler in self._on_message_handlers:
                    try:
                        console.log(f"ServerPush: Calling handler {handler}")
                        result = handler(event) # Pass the full event or just data? Usually event.
                        # Handle async handlers
                        if inspect.iscoroutine(result):
                            console.log(f"ServerPush: Handler returned coroutine, scheduling task")
                            asyncio.create_task(result)
                        else:
                            console.log(f"ServerPush: Handler completed synchronously")
                    except Exception as e:
                        console.error(f"Error in on_message handler: {e}", exc_info=True)

            except Exception as e:
                console.error(f"Error processing ServerPush message: {e}", exc_info=True)

        def on_error(event):
            # EventSource attempts reconnect automatically, but we should notify.
            # Extract useful error information
            error_info = {
                'type': getattr(event, 'type', 'unknown'),
                'target_readyState': getattr(self._es, 'readyState', None) if self._es else None,
                'target_url': getattr(self._es, 'url', None) if self._es else None,
                'target_withCredentials': getattr(self._es, 'withCredentials', None) if self._es else None,
            }
            
            # EventSource readyState: 0=CONNECTING, 1=OPEN, 2=CLOSED
            # An error event doesn't necessarily mean failure - EventSource auto-reconnects
            ready_state = error_info['target_readyState']
            
            # Track reconnection attempts to prevent loops
            from js import Date
            current_time = Date.now()  # milliseconds
            
            if ready_state == ES_CLOSED:
                # Connection was closed (could be intentional or error)
                # Check if we're in a reconnection loop
                if current_time - self._last_reconnect_time < self._reconnect_window:
                    self._reconnect_count += 1
                else:
                    self._reconnect_count = 1
                
                self._last_reconnect_time = current_time
                
                if self._reconnect_count > self._max_reconnects:
                    console.error(f"ServerPush: Too many reconnection attempts ({self._reconnect_count}), stopping. URL: {self.url}")
                    self.set_state(ServerPushState.CLOSED)
                    if self._es:
                        self._es.close()
                    return
                
                console.warn(f"ServerPush connection closed (reconnect {self._reconnect_count}/{self._max_reconnects}): {self.url}")
                self.set_state(ServerPushState.CLOSED)
            elif ready_state == ES_CONNECTING:
                # EventSource is attempting to reconnect
                # Only log if not in rapid reconnect loop
                if self._reconnect_count <= 3:
                    console.log(f"ServerPush reconnecting: {self.url}")
                self.set_state(ServerPushState.CONNECTING)
            else:
                # Other error state
                console.error(f"ServerPush error (readyState={ready_state}): {error_info}")
            
            for handler in self._on_error_handlers:
                try:
                    result = handler(event)
                    # Handle async handlers
                    if inspect.iscoroutine(result):
                        asyncio.create_task(result)
                except Exception as e:
                    console.error(f"Error in on_error handler: {e}", exc_info=True)

        self._js_handlers = {
            'open': self._create_js_proxy(on_open),
            'message': self._create_js_proxy(on_message),
            'error': self._create_js_proxy(on_error)
        }

        # Verify EventSource supports these event types
        console.log(f"ServerPush: Setting up event listeners for EventSource at {self.url}")
        console.log(f"ServerPush: EventSource readyState before listeners: {self._es.readyState}")
        console.log(f"ServerPush: Number of message handlers registered: {len(self._on_message_handlers)}")
        
        self._es.addEventListener('open', self._js_handlers['open'])
        self._es.addEventListener('message', self._js_handlers['message'])
        self._es.addEventListener('error', self._js_handlers['error'])
        
        console.log(f"ServerPush: Event listeners registered. readyState: {self._es.readyState}")
        
        # Log EventSource properties for debugging
        console.log(f"ServerPush: EventSource URL: {getattr(self._es, 'url', 'N/A')}")
        console.log(f"ServerPush: EventSource withCredentials: {getattr(self._es, 'withCredentials', 'N/A')}")

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
