import json
import asyncio
from enum import Enum
from typing import Any, Optional, Callable, Dict, List, Union
from pyodide.ffi import create_proxy, JsProxy
from js import WebSocket, console, ArrayBuffer, Uint8Array

# WebSocket readyState constants
WS_CONNECTING = 0
WS_OPEN = 1
WS_CLOSING = 2
WS_CLOSED = 3

from metafor.core import create_signal, Signal
from .exceptions import ChannelError, ChannelConnectionError, ChannelMessageError


class ChannelState(Enum):
    """WebSocket connection states."""
    CONNECTING = "connecting"
    OPEN = "open"
    CLOSING = "closing"
    CLOSED = "closed"


class Channel:
    """
    A WebSocket channel implementation for Metafor.
    Provides a Pythonic API for WebSocket communication using native JavaScript WebSockets through Pyodide.
    """
    
    def __init__(
        self,
        url: str,
        protocols: Optional[List[str]] = None,
        auto_reconnect: bool = False,
        reconnect_delay: float = 1.0,
        max_reconnect_attempts: Optional[int] = None
    ):
        """
        Initialize a WebSocket channel.
        
        Args:
            url: WebSocket server URL (ws:// or wss://)
            protocols: Optional list of subprotocols
            auto_reconnect: Whether to automatically reconnect on disconnect
            reconnect_delay: Delay in seconds between reconnect attempts
            max_reconnect_attempts: Maximum number of reconnect attempts (None for unlimited)
        """
        self.url = url
        self.protocols = protocols or []
        self.auto_reconnect = auto_reconnect
        self.reconnect_delay = reconnect_delay
        self.max_reconnect_attempts = max_reconnect_attempts
        self._reconnect_attempts = 0
        
        # Reactive state signals
        self.state_signal, self.set_state = create_signal(ChannelState.CLOSED)
        self.ready_state_signal, self.set_ready_state = create_signal(0)  # WebSocket.readyState
        
        # WebSocket instance
        self._ws: Optional[JsProxy] = None
        
        # Event handlers
        self._on_open_handlers: List[Callable] = []
        self._on_message_handlers: List[Callable] = []
        self._on_error_handlers: List[Callable] = []
        self._on_close_handlers: List[Callable] = []
        
        # Message queue for messages sent before connection is open
        self._message_queue: List[Union[str, bytes, Dict, Any]] = []
        
        # JavaScript event handler proxies
        self._js_handlers = {}
        
        # Room management
        self._rooms: set = set()  # Set of rooms this channel has joined
        self._room_handlers: Dict[str, List[Callable]] = {}  # Room-specific message handlers
    
    @property
    def state(self) -> ChannelState:
        """Get current connection state."""
        return self.state_signal()
    
    @property
    def ready_state(self) -> int:
        """Get WebSocket readyState (0=CONNECTING, 1=OPEN, 2=CLOSING, 3=CLOSED)."""
        return self.ready_state_signal()
    
    @property
    def is_connected(self) -> bool:
        """Check if channel is connected."""
        return self.state == ChannelState.OPEN
    
    @property
    def is_connecting(self) -> bool:
        """Check if channel is connecting."""
        return self.state == ChannelState.CONNECTING
    
    def _create_js_proxy(self, handler: Callable) -> JsProxy:
        """Create a JavaScript proxy for an event handler."""
        return create_proxy(handler)
    
    def _setup_event_handlers(self):
        """Set up JavaScript event handlers."""
        if not self._ws:
            return
        
        # Open handler
        def on_open(event):
            self.set_state(ChannelState.OPEN)
            self.set_ready_state(self._ws.readyState)
            self._reconnect_attempts = 0  # Reset on successful connection
            
            # Rejoin all rooms after reconnection
            rooms_to_rejoin = list(self._rooms)
            for room in rooms_to_rejoin:
                asyncio.create_task(self.send({"type": "_join", "room": room}))
            
            # Send queued messages
            while self._message_queue:
                item = self._message_queue.pop(0)
                if isinstance(item, tuple):
                    msg, room = item
                    asyncio.create_task(self._send_immediate(msg, room))
                else:
                    asyncio.create_task(self._send_immediate(item))
            
            # Call Python handlers
            for handler in self._on_open_handlers:
                try:
                    # Check if handler accepts arguments
                    import inspect
                    try:
                        sig = inspect.signature(handler)
                        param_count = len(sig.parameters)
                        if param_count > 0:
                            handler(event)
                        else:
                            handler()
                    except (ValueError, TypeError):
                        # If signature inspection fails, try with event first, then without
                        try:
                            handler(event)
                        except TypeError:
                            handler()
                except Exception as e:
                    console.error(f"Error in on_open handler: {e}")
        
        # Message handler
        def on_message(event):
            try:
                # Handle different message types
                if hasattr(event, 'data'):
                    data = event.data
                    
                    # Try to parse as JSON if it's a string
                    if isinstance(data, str):
                        try:
                            parsed = json.loads(data)
                            message = parsed
                        except (json.JSONDecodeError, TypeError):
                            message = data
                    elif isinstance(data, (ArrayBuffer, Uint8Array)):
                        # Binary data
                        if isinstance(data, ArrayBuffer):
                            uint8 = Uint8Array.new(data)
                        else:
                            uint8 = data
                        message = bytes(uint8)
                    else:
                        message = data
                    
                    # In Socket.IO style, the server only sends messages to clients in the appropriate rooms.
                    # So if we receive a message, we trust it's for a room we're in.
                    # However, if the server includes room metadata, we can use it for routing.
                    
                    message_room = None
                    if isinstance(message, dict):
                        # Check if server included room metadata (optional, for routing)
                        if "_room" in message:
                            message_room = message["_room"]
                            # Remove room metadata from message before passing to handlers
                            message = {k: v for k, v in message.items() if k != "_room"}
                        
                        # Also check for explicit room field (alternative protocol)
                        if "room" in message and message_room is None:
                            message_room = message.get("room")
                    
                    # Call room-specific handlers if room metadata is present
                    if message_room and message_room in self._room_handlers:
                        for handler in self._room_handlers[message_room]:
                            try:
                                handler(message)
                            except Exception as e:
                                console.error(f"Error in room handler for '{message_room}': {e}")
                    
                    # Call general message handlers (always called)
                    # In Socket.IO style, if you're in a room and receive a message, 
                    # it's implicitly for that room, so general handlers receive all messages
                    for handler in self._on_message_handlers:
                        try:
                            handler(message)
                        except Exception as e:
                            console.error(f"Error in on_message handler: {e}")
            except Exception as e:
                console.error(f"Error processing message: {e}")
                for handler in self._on_error_handlers:
                    try:
                        handler(ChannelMessageError(f"Failed to process message: {e}"))
                    except Exception as handler_error:
                        console.error(f"Error in error handler: {handler_error}")
        
        # Error handler
        def on_error(event):
            error = ChannelConnectionError("WebSocket error occurred")
            self.set_state(ChannelState.CLOSED)
            self.set_ready_state(self._ws.readyState if self._ws else WS_CLOSED)
            
            for handler in self._on_error_handlers:
                try:
                    handler(error)
                except Exception as e:
                    console.error(f"Error in on_error handler: {e}")
        
        # Close handler
        def on_close(event):
            was_open = self.state == ChannelState.OPEN
            self.set_state(ChannelState.CLOSED)
            self.set_ready_state(self._ws.readyState if self._ws else WS_CLOSED)
            
            # Clean up JavaScript handlers
            self._cleanup_handlers()
            
            # Call Python handlers
            for handler in self._on_close_handlers:
                try:
                    # Check if handler accepts arguments
                    import inspect
                    try:
                        sig = inspect.signature(handler)
                        param_count = len(sig.parameters)
                        if param_count > 0:
                            handler(event)
                        else:
                            handler()
                    except (ValueError, TypeError):
                        # If signature inspection fails, try with event first, then without
                        try:
                            handler(event)
                        except TypeError:
                            handler()
                except Exception as e:
                    console.error(f"Error in on_close handler: {e}")
            
            # Auto-reconnect if enabled and connection was open
            if was_open and self.auto_reconnect:
                if self.max_reconnect_attempts is None or self._reconnect_attempts < self.max_reconnect_attempts:
                    self._reconnect_attempts += 1
                    asyncio.create_task(self._reconnect())
        
        # Create proxies and attach handlers
        self._js_handlers = {
            'open': self._create_js_proxy(on_open),
            'message': self._create_js_proxy(on_message),
            'error': self._create_js_proxy(on_error),
            'close': self._create_js_proxy(on_close)
        }
        
        self._ws.addEventListener('open', self._js_handlers['open'])
        self._ws.addEventListener('message', self._js_handlers['message'])
        self._ws.addEventListener('error', self._js_handlers['error'])
        self._ws.addEventListener('close', self._js_handlers['close'])
    
    def _cleanup_handlers(self):
        """Remove JavaScript event handlers."""
        if not self._ws:
            return
        
        for event_type, handler in self._js_handlers.items():
            try:
                self._ws.removeEventListener(event_type, handler)
            except:
                pass
        
        self._js_handlers.clear()
    
    async def connect(self) -> None:
        """
        Connect to the WebSocket server.
        
        Raises:
            ChannelConnectionError: If connection fails
        """
        if self._ws and self._ws.readyState == WS_OPEN:
            return  # Already connected
        
        if self._ws:
            await self.close()
        
        try:
            self.set_state(ChannelState.CONNECTING)
            
            # Create WebSocket instance
            if self.protocols:
                self._ws = WebSocket.new(self.url, self.protocols)
            else:
                self._ws = WebSocket.new(self.url)
            
            self.set_ready_state(self._ws.readyState)
            
            # Set up event handlers
            self._setup_event_handlers()
            
            # Wait for connection to open
            await self._wait_for_open()
            
        except Exception as e:
            self.set_state(ChannelState.CLOSED)
            self.set_ready_state(WS_CLOSED)
            raise ChannelConnectionError(f"Failed to connect: {e}") from e
    
    async def _wait_for_open(self, timeout: float = 10.0):
        """Wait for WebSocket to open."""
        import time
        start_time = time.time()
        
        while self._ws and self._ws.readyState != WS_OPEN:
            if time.time() - start_time > timeout:
                raise ChannelConnectionError("Connection timeout")
            await asyncio.sleep(0.1)
    
    async def _reconnect(self):
        """Attempt to reconnect to the WebSocket server."""
        await asyncio.sleep(self.reconnect_delay)
        try:
            await self.connect()
        except Exception as e:
            console.error(f"Reconnection attempt {self._reconnect_attempts} failed: {e}")
    
    async def send(self, message: Union[str, bytes, Dict, Any], room: Optional[str] = None) -> None:
        """
        Send a message through the WebSocket.
        
        Args:
            message: Message to send. Can be:
                - str: Sent as text
                - bytes: Sent as binary
                - dict: Serialized to JSON and sent as text
                - Any: Converted to string and sent as text
            room: Optional room name to send message to (server-side routing)
        
        Raises:
            ChannelMessageError: If message cannot be sent
        """
        if not self._ws:
            raise ChannelMessageError("WebSocket not initialized. Call connect() first.")
        
        # If not connected, queue the message if auto_reconnect is enabled
        if self._ws.readyState != WS_OPEN:
            if self.auto_reconnect:
                self._message_queue.append((message, room))
                return
            else:
                raise ChannelMessageError("WebSocket is not open. Current state: " + str(self.state))
        
        try:
            await self._send_immediate(message, room)
        except Exception as e:
            raise ChannelMessageError(f"Failed to send message: {e}") from e
    
    async def send_to(self, room: str, message: Union[str, bytes, Dict, Any]) -> None:
        """
        Send a message to a specific room.
        
        Args:
            room: Room name to send message to
            message: Message to send
        
        Raises:
            ChannelMessageError: If message cannot be sent
        """
        await self.send(message, room=room)
    
    async def _send_immediate(self, message: Union[str, bytes, Dict, Any], room: Optional[str] = None) -> None:
        """Send a message immediately (assumes connection is open)."""
        # If room is specified, wrap message with room metadata
        if room:
            if isinstance(message, dict):
                message = {**message, "_room": room}
            elif isinstance(message, str):
                try:
                    # Try to parse as JSON and add room
                    parsed = json.loads(message)
                    if isinstance(parsed, dict):
                        parsed["_room"] = room
                        message = json.dumps(parsed)
                except (json.JSONDecodeError, TypeError):
                    # If not JSON, wrap in a dict
                    message = json.dumps({"message": message, "_room": room})
            else:
                # For other types, wrap in dict
                message = {"data": message, "_room": room}
        
        if isinstance(message, dict):
            # Serialize dict to JSON
            message = json.dumps(message)
        
        if isinstance(message, bytes):
            # Send as binary
            self._ws.send(message)
        else:
            # Send as text
            self._ws.send(str(message))
    
    async def close(self, code: int = 1000, reason: str = "Normal closure") -> None:
        """
        Close the WebSocket connection.
        
        Args:
            code: Close code (default: 1000)
            reason: Close reason (default: "Normal closure")
        """
        if not self._ws:
            return
        
        if self._ws.readyState in [WS_CLOSING, WS_CLOSED]:
            return
        
        self.set_state(ChannelState.CLOSING)
        self._ws.close(code, reason)
        
        # Wait for close event
        import time
        start_time = time.time()
        while self._ws.readyState != WS_CLOSED and (time.time() - start_time) < 5.0:
            await asyncio.sleep(0.1)
        
        self._cleanup_handlers()
        self._ws = None
        self.set_state(ChannelState.CLOSED)
        self.set_ready_state(3)  # CLOSED
    
    def on_open(self, handler: Callable) -> Callable:
        """
        Register a handler for the open event.
        
        Args:
            handler: Function to call when connection opens
        
        Returns:
            The handler function (for easy removal)
        """
        self._on_open_handlers.append(handler)
        return handler
    
    def on_message(self, handler: Callable) -> Callable:
        """
        Register a handler for incoming messages.
        
        Args:
            handler: Function to call when a message is received.
                    Receives the message as argument (parsed JSON if possible, otherwise raw)
        
        Returns:
            The handler function (for easy removal)
        """
        self._on_message_handlers.append(handler)
        return handler
    
    def on_error(self, handler: Callable) -> Callable:
        """
        Register a handler for errors.
        
        Args:
            handler: Function to call when an error occurs.
                    Receives a ChannelError as argument
        
        Returns:
            The handler function (for easy removal)
        """
        self._on_error_handlers.append(handler)
        return handler
    
    def on_close(self, handler: Callable) -> Callable:
        """
        Register a handler for the close event.
        
        Args:
            handler: Function to call when connection closes
        
        Returns:
            The handler function (for easy removal)
        """
        self._on_close_handlers.append(handler)
        return handler
    
    def remove_handler(self, handler: Callable) -> bool:
        """
        Remove an event handler.
        
        Args:
            handler: Handler function to remove
        
        Returns:
            True if handler was found and removed, False otherwise
        """
        removed = False
        if handler in self._on_open_handlers:
            self._on_open_handlers.remove(handler)
            removed = True
        if handler in self._on_message_handlers:
            self._on_message_handlers.remove(handler)
            removed = True
        if handler in self._on_error_handlers:
            self._on_error_handlers.remove(handler)
            removed = True
        if handler in self._on_close_handlers:
            self._on_close_handlers.remove(handler)
            removed = True
        return removed
    
    def clear_handlers(self):
        """Remove all event handlers."""
        self._on_open_handlers.clear()
        self._on_message_handlers.clear()
        self._on_error_handlers.clear()
        self._on_close_handlers.clear()
        self._room_handlers.clear()
    
    async def join(self, room: str) -> None:
        """
        Join a room (topic/channel).
        Sends a join command to the server. The server should then only send
        messages for this room to this client.
        
        Note: In Socket.IO style, the server filters messages server-side.
        If you receive a message, it's already for a room you're in.
        Room-specific handlers are optional and work if the server includes room metadata.
        
        Args:
            room: Room name to join
        
        Example:
            await channel.join("chat-room-1")
        """
        if room not in self._rooms:
            self._rooms.add(room)
            # Send join command to server
            await self.send({"type": "_join", "room": room})
    
    async def leave(self, room: str) -> None:
        """
        Leave a room (topic/channel).
        Sends a leave command to the server.
        
        Args:
            room: Room name to leave
        
        Example:
            await channel.leave("chat-room-1")
        """
        if room in self._rooms:
            self._rooms.remove(room)
            # Send leave command to server
            await self.send({"type": "_leave", "room": room})
            # Clear room-specific handlers
            if room in self._room_handlers:
                del self._room_handlers[room]
    
    def is_in_room(self, room: str) -> bool:
        """
        Check if channel is currently in a room.
        
        Args:
            room: Room name to check
        
        Returns:
            True if in the room, False otherwise
        """
        return room in self._rooms
    
    def get_rooms(self) -> List[str]:
        """
        Get list of rooms this channel has joined.
        
        Returns:
            List of room names
        """
        return list(self._rooms)
    
    def on_room_message(self, room: str, handler: Callable) -> Callable:
        """
        Register a handler for messages from a specific room.
        
        Note: This only works if the server includes room metadata in messages.
        In pure Socket.IO style, the server filters server-side and doesn't include
        room metadata. Use general on_message() handlers in that case.
        
        Args:
            room: Room name to listen to
            handler: Function to call when a message is received from this room.
                    Receives the message as argument (parsed JSON if possible, otherwise raw)
        
        Returns:
            The handler function (for easy removal)
        
        Example:
            channel.on_room_message("chat-room-1", lambda msg: print(f"Room message: {msg}"))
        """
        if room not in self._room_handlers:
            self._room_handlers[room] = []
        self._room_handlers[room].append(handler)
        return handler
    
    def remove_room_handler(self, room: str, handler: Callable) -> bool:
        """
        Remove a room-specific message handler.
        
        Args:
            room: Room name
            handler: Handler function to remove
        
        Returns:
            True if handler was found and removed, False otherwise
        """
        if room in self._room_handlers and handler in self._room_handlers[room]:
            self._room_handlers[room].remove(handler)
            if not self._room_handlers[room]:
                del self._room_handlers[room]
            return True
        return False
    
    def clear_room_handlers(self, room: Optional[str] = None):
        """
        Clear room-specific message handlers.
        
        Args:
            room: Room name to clear handlers for. If None, clears all room handlers.
        """
        if room:
            if room in self._room_handlers:
                del self._room_handlers[room]
        else:
            self._room_handlers.clear()

