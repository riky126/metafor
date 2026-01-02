# Channels - WebSocket Communication

Metafor Channels provide a Pythonic API for WebSocket communication using native JavaScript WebSockets through Pyodide. Channels support room/topic management similar to Socket.IO, making it easy to build real-time applications.

## Table of Contents

- [Basic Usage](#basic-usage)
- [Connection Management](#connection-management)
- [Sending Messages](#sending-messages)
- [Receiving Messages](#receiving-messages)
- [Rooms and Topics](#rooms-and-topics)
- [Event Handlers](#event-handlers)
- [Using in Components](#using-in-components)
- [Error Handling](#error-handling)
- [Auto-Reconnect](#auto-reconnect)
- [Server-Side Protocol](#server-side-protocol)
- [Best Practices](#best-practices)

## Basic Usage

### Creating a Channel

```python
from metafor.channels import Channel

# Create a channel
channel = Channel("ws://localhost:8000/ws")

# With auto-reconnect
channel = Channel(
    "ws://localhost:8000/ws",
    auto_reconnect=True,
    reconnect_delay=2.0,
    max_reconnect_attempts=5
)
```

### Connecting

```python
import asyncio

async def main():
    await channel.connect()
    print("Connected!")

asyncio.run(main())
```

### Sending Messages

```python
# Send a dictionary (auto-serialized to JSON)
await channel.send({"type": "message", "text": "Hello"})

# Send plain text
await channel.send("Hello, World!")

# Send binary data
await channel.send(b"Binary data")
```

### Receiving Messages

```python
def handle_message(msg):
    print(f"Received: {msg}")

channel.on_message(handle_message)
```

### Closing Connection

```python
await channel.close()
```

## Connection Management

### Connection States

Channels track connection state reactively:

```python
from metafor.channels import ChannelState

# Check state
if channel.state == ChannelState.OPEN:
    print("Connected")

# Reactive state signal
from metafor.core import track

state = track(lambda: channel.state_signal())
print(f"Current state: {state}")
```

### State Properties

```python
# Check if connected
if channel.is_connected:
    print("Channel is connected")

# Check if connecting
if channel.is_connecting:
    print("Channel is connecting")

# Get ready state (0=CONNECTING, 1=OPEN, 2=CLOSING, 3=CLOSED)
ready_state = channel.ready_state
```

## Sending Messages

### Basic Sending

```python
# Send without room (global message)
await channel.send({"text": "Hello"})

# Send plain text
await channel.send("Hello, World!")

# Send binary
await channel.send(b"Binary data")
```

### Sending to Rooms

```python
# Method 1: Using room parameter
await channel.send({"text": "Hello"}, room="chat-room")

# Method 2: Using send_to() convenience method
await channel.send_to("chat-room", {"text": "Hello"})
```

### Message Types

Channels automatically handle different message types:

- **Dictionary**: Serialized to JSON
- **String**: Sent as text
- **Bytes**: Sent as binary
- **Other types**: Converted to string

## Receiving Messages

### General Message Handler

```python
def handle_message(msg):
    # msg is automatically parsed if JSON, otherwise raw
    if isinstance(msg, dict):
        print(f"Received JSON: {msg}")
    else:
        print(f"Received: {msg}")

channel.on_message(handle_message)
```

### Multiple Handlers

You can register multiple handlers:

```python
channel.on_message(lambda msg: print(f"Handler 1: {msg}"))
channel.on_message(lambda msg: print(f"Handler 2: {msg}"))
```

### Removing Handlers

```python
handler = channel.on_message(lambda msg: print(msg))
channel.remove_handler(handler)
```

## Rooms and Topics

Rooms allow you to organize messages into channels/topics, similar to Socket.IO.

### Joining Rooms

```python
# Join a room
await channel.join("chat-room-1")
await channel.join("notifications")
```

### Leaving Rooms

```python
# Leave a room
await channel.leave("chat-room-1")
```

### Checking Room Membership

```python
# Check if in a room
if channel.is_in_room("chat-room-1"):
    print("In chat-room-1")

# Get all joined rooms
rooms = channel.get_rooms()
print(f"Joined rooms: {rooms}")
```

### Sending to Rooms

```python
# Send to specific room
await channel.send_to("chat-room-1", {"text": "Hello room!"})

# Or use room parameter
await channel.send({"text": "Hello"}, room="chat-room-1")
```

### Room-Specific Handlers

If your server includes room metadata in messages, you can use room-specific handlers:

```python
# Handler for specific room
channel.on_room_message("chat-room-1", lambda msg: print(f"Chat: {msg}"))
channel.on_room_message("notifications", lambda msg: print(f"Notification: {msg}"))
```

**Note**: Room-specific handlers only work if the server includes room metadata. In pure Socket.IO style, the server filters server-side and doesn't include metadata. Use general `on_message()` handlers in that case.

## Event Handlers

### Connection Events

```python
# On connection open
channel.on_open(lambda: print("Connected!"))

# On connection close
channel.on_close(lambda: print("Disconnected!"))

# On error
channel.on_error(lambda error: print(f"Error: {error}"))
```

### Message Events

```python
# General message handler
channel.on_message(lambda msg: print(f"Message: {msg}"))

# Room-specific handler (if server includes room metadata)
channel.on_room_message("room-name", lambda msg: print(f"Room message: {msg}"))
```

### Handler Management

```python
# Remove a specific handler
handler = channel.on_message(my_handler)
channel.remove_handler(handler)

# Clear all handlers
channel.clear_handlers()

# Clear room handlers
channel.clear_room_handlers()  # All rooms
channel.clear_room_handlers("room-name")  # Specific room
```

## Using in Components

### Basic Component Example

```python
@component("ChatComponent") @props {
    from metafor.core import create_signal, on_mount, on_dispose
    from metafor.channels import Channel
    import asyncio
    
    # State
    messages, set_messages = create_signal([])
    input_text, set_input_text = create_signal("")
    
    # Create channel
    channel = Channel("ws://localhost:8000/ws", auto_reconnect=True)
    
    # Setup handlers
    channel.on_message(lambda msg: set_messages([*messages(), str(msg)]))
    
    # Connect on mount
    on_mount(lambda: asyncio.create_task(channel.connect()))
    
    # Cleanup on dispose
    on_dispose(lambda: asyncio.create_task(channel.close()))
    
    # Send message
    async def send():
        if input_text().strip():
            await channel.send({"text": input_text()})
            set_input_text("")
}

@ptml {
    <div>
        <For each=@{messages}>
            @{lambda msg: <p>@{msg}</p>}
        </For>
        <input 
            value=@{input_text}
            oninput=@{lambda e: set_input_text(e.target.value)}
        />
        <button onclick=@{lambda: asyncio.create_task(send())}>Send</button>
    </div>
}
```

### Component with Rooms

```python
@component("RoomChat") @props {
    from metafor.core import create_signal, on_mount, on_dispose
    from metafor.channels import Channel
    import asyncio
    
    messages, set_messages = create_signal([])
    current_room, set_current_room = create_signal("general")
    input_text, set_input_text = create_signal("")
    
    channel = Channel("ws://localhost:8000/ws", auto_reconnect=True)
    
    # Message handler
    def handle_message(msg):
        new_messages = list(messages())
        new_messages.append({
            "room": current_room(),
            "text": msg.get("text", str(msg)) if isinstance(msg, dict) else str(msg)
        })
        set_messages(new_messages)
    
    channel.on_message(handle_message)
    
    # Connect and join room on mount
    async def setup():
        await channel.connect()
        await channel.join(current_room())
    
    on_mount(lambda: asyncio.create_task(setup()))
    on_dispose(lambda: asyncio.create_task(channel.close()))
    
    # Switch rooms
    async def switch_room(room_name):
        if channel.is_in_room(current_room()):
            await channel.leave(current_room())
        await channel.join(room_name)
        set_current_room(room_name)
        set_messages([])
    
    # Send message
    async def send():
        if input_text().strip():
            await channel.send_to(current_room(), {"text": input_text()})
            set_input_text("")
}

@ptml {
    <div>
        <div>
            <button onclick=@{lambda: asyncio.create_task(switch_room("general"))}>
                General
            </button>
            <button onclick=@{lambda: asyncio.create_task(switch_room("tech"))}>
                Tech
            </button>
        </div>
        <div>
            <h3>Room: @{current_room}</h3>
            <For each=@{messages}>
                @{lambda msg: <p>@{msg.get('text', '')}</p>}
            </For>
        </div>
        <input 
            value=@{input_text}
            oninput=@{lambda e: set_input_text(e.target.value)}
        />
        <button onclick=@{lambda: asyncio.create_task(send())}>Send</button>
    </div>
}
```

## Error Handling

### Error Handler

```python
from metafor.channels import ChannelConnectionError, ChannelMessageError

def handle_error(error):
    if isinstance(error, ChannelConnectionError):
        print(f"Connection error: {error}")
    elif isinstance(error, ChannelMessageError):
        print(f"Message error: {error}")
    else:
        print(f"Error: {error}")

channel.on_error(handle_error)
```

### Try-Catch for Operations

```python
try:
    await channel.connect()
except ChannelConnectionError as e:
    print(f"Failed to connect: {e}")

try:
    await channel.send({"text": "Hello"})
except ChannelMessageError as e:
    print(f"Failed to send: {e}")
```

## Auto-Reconnect

### Configuration

```python
channel = Channel(
    "ws://localhost:8000/ws",
    auto_reconnect=True,           # Enable auto-reconnect
    reconnect_delay=2.0,            # Wait 2 seconds between attempts
    max_reconnect_attempts=5        # Max 5 attempts (None for unlimited)
)
```

### Behavior

- Automatically reconnects on disconnect
- Rejoins all previously joined rooms
- Resends queued messages (if sent while disconnected)
- Resets attempt counter on successful connection

### Manual Reconnection

```python
# Disable auto-reconnect and handle manually
channel = Channel("ws://localhost:8000/ws", auto_reconnect=False)

channel.on_close(lambda: asyncio.create_task(reconnect()))

async def reconnect():
    await asyncio.sleep(2)
    try:
        await channel.connect()
        # Rejoin rooms manually
        for room in ["room1", "room2"]:
            await channel.join(room)
    except Exception as e:
        print(f"Reconnect failed: {e}")
```

## Server-Side Protocol

### Room Management Messages

The client sends special messages for room management:

**Join Room:**
```json
{
  "type": "_join",
  "room": "room-name"
}
```

**Leave Room:**
```json
{
  "type": "_leave",
  "room": "room-name"
}
```

### Messages with Room Metadata

When sending to a room, messages include room metadata:

```json
{
  "_room": "room-name",
  "text": "Hello",
  "user": "alice"
}
```

### Server Implementation

Your server should:

1. **Handle join/leave commands:**
   ```python
   # Pseudocode
   if message["type"] == "_join":
       add_client_to_room(websocket, message["room"])
   elif message["type"] == "_leave":
       remove_client_from_room(websocket, message["room"])
   ```

2. **Route messages by room:**
   ```python
   # Pseudocode
   if "_room" in message:
       room = message["_room"]
       broadcast_to_room(room, message)
   else:
       broadcast_to_all(message)
   ```

3. **Filter messages server-side (Socket.IO style):**
   - Only send messages to clients in the appropriate rooms
   - Don't include room metadata in messages (optional)
   - Client trusts that received messages are for rooms it's in

## Best Practices

### 1. Always Clean Up

```python
on_mount(lambda: asyncio.create_task(channel.connect()))
on_dispose(lambda: asyncio.create_task(channel.close()))
```

### 2. Use Auto-Reconnect for Production

```python
channel = Channel(
    url,
    auto_reconnect=True,
    reconnect_delay=2.0,
    max_reconnect_attempts=None  # Unlimited for production
)
```

### 3. Handle Connection State in UI

```python
is_connected, set_is_connected = create_signal(False)

channel.on_open(lambda: set_is_connected(True))
channel.on_close(lambda: set_is_connected(False))

# In template
<Show when=@{is_connected} fallback=@{<p>Connecting...</p>}>
    <div>Connected!</div>
</Show>
```

### 4. Queue Messages When Disconnected

With `auto_reconnect=True`, messages are automatically queued. Otherwise:

```python
async def safe_send(message):
    if channel.is_connected:
        await channel.send(message)
    else:
        # Queue or handle error
        print("Not connected, message not sent")
```

### 5. Use Room-Specific Handlers Sparingly

In Socket.IO style, the server filters messages, so room-specific handlers aren't needed. Use them only if:
- Your server includes room metadata
- You need client-side routing for debugging
- You're using a different protocol

### 6. Rejoin Rooms After Reconnect

With `auto_reconnect=True`, rooms are automatically rejoined. Otherwise:

```python
channel.on_open(lambda: asyncio.create_task(rejoin_rooms()))

async def rejoin_rooms():
    for room in ["room1", "room2"]:
        await channel.join(room)
```

### 7. Handle Errors Gracefully

```python
channel.on_error(lambda error: console.error(f"Channel error: {error}"))

try:
    await channel.send(message)
except ChannelMessageError as e:
    # Handle error, maybe retry or show user
    show_error_to_user("Failed to send message")
```

## API Reference

### Channel Class

```python
Channel(
    url: str,
    protocols: Optional[List[str]] = None,
    auto_reconnect: bool = False,
    reconnect_delay: float = 1.0,
    max_reconnect_attempts: Optional[int] = None
)
```

### Methods

- `async connect() -> None` - Connect to WebSocket server
- `async send(message, room=None) -> None` - Send a message
- `async send_to(room, message) -> None` - Send message to room
- `async close(code=1000, reason="Normal closure") -> None` - Close connection
- `async join(room: str) -> None` - Join a room
- `async leave(room: str) -> None` - Leave a room
- `is_in_room(room: str) -> bool` - Check room membership
- `get_rooms() -> List[str]` - Get all joined rooms
- `on_open(handler) -> Callable` - Register open handler
- `on_close(handler) -> Callable` - Register close handler
- `on_message(handler) -> Callable` - Register message handler
- `on_error(handler) -> Callable` - Register error handler
- `on_room_message(room, handler) -> Callable` - Register room handler
- `remove_handler(handler) -> bool` - Remove a handler
- `clear_handlers() -> None` - Clear all handlers

### Properties

- `state: ChannelState` - Current connection state
- `ready_state: int` - WebSocket readyState
- `is_connected: bool` - Whether connected
- `is_connecting: bool` - Whether connecting

### Signals

- `state_signal` - Reactive state signal
- `ready_state_signal` - Reactive readyState signal

## Testing with Public WebSocket Servers

### Echo Test Servers

These servers echo back whatever you send:

```python
# Simple echo server
channel = Channel("wss://echo.websocket.org")
channel.on_message(lambda msg: print(f"Echo: {msg}"))
await channel.connect()
await channel.send("Hello, World!")
```

**Available Echo Servers:**
- `wss://echo.websocket.org` - Most popular, reliable
- `wss://echo.websocket.events` - Alternative echo server
- `ws://echo.websocket.org` - Non-secure version

### WebSocket Test Servers

**1. WebSocket.org Echo Test:**
```python
channel = Channel("wss://echo.websocket.org")
```

**2. Postman Echo Server:**
```python
channel = Channel("wss://ws.postman-echo.com/raw")
```

**3. Socket.IO Test Server:**
```python
# Note: This requires Socket.IO protocol, may need adjustments
channel = Channel("wss://socketio-chat-h9jt.herokuapp.com/")
```

### Local Testing

For local testing, you can use simple WebSocket servers:

**Python (using websockets library):**
```python
import asyncio
from websockets.server import serve

async def echo(websocket):
    async for message in websocket:
        await websocket.send(f"Echo: {message}")

async def main():
    async with serve(echo, "localhost", 8765):
        await asyncio.Future()  # run forever

asyncio.run(main())
```

Then connect with:
```python
channel = Channel("ws://localhost:8765")
```

**Node.js (using ws library):**
```javascript
const WebSocket = require('ws');
const wss = new WebSocket.Server({ port: 8080 });

wss.on('connection', function connection(ws) {
  ws.on('message', function message(data) {
    console.log('received: %s', data);
    ws.send(`Echo: ${data}`);
  });
  
  ws.send('Connected!');
});
```

### Testing Room Support

For testing rooms, you'll need a custom server that handles room management. Here's a simple Python example:

```python
import asyncio
import json
from websockets.server import serve

rooms = {}  # room_name -> set of websockets

async def handle_client(websocket):
    client_rooms = set()
    
    async for message in websocket:
        try:
            data = json.loads(message)
            
            # Handle join
            if data.get("type") == "_join":
                room = data.get("room")
                if room not in rooms:
                    rooms[room] = set()
                rooms[room].add(websocket)
                client_rooms.add(room)
                await websocket.send(json.dumps({"status": "joined", "room": room}))
            
            # Handle leave
            elif data.get("type") == "_leave":
                room = data.get("room")
                if room in rooms:
                    rooms[room].discard(websocket)
                client_rooms.discard(room)
                await websocket.send(json.dumps({"status": "left", "room": room}))
            
            # Handle room message
            elif "_room" in data:
                room = data["_room"]
                if room in rooms:
                    # Broadcast to all clients in room
                    for client in rooms[room]:
                        if client != websocket:  # Don't echo to sender
                            await client.send(json.dumps(data))
            
            # Handle regular message
            else:
                await websocket.send(json.dumps({"echo": data}))
                
        except json.JSONDecodeError:
            await websocket.send(f"Echo: {message}")
    
    # Cleanup on disconnect
    for room in client_rooms:
        if room in rooms:
            rooms[room].discard(websocket)

async def main():
    async with serve(handle_client, "localhost", 8765):
        print("WebSocket server running on ws://localhost:8765")
        await asyncio.Future()

asyncio.run(main())
```

### Quick Test Example

```python
from metafor.channels import Channel
import asyncio

async def test():
    # Connect to echo server
    channel = Channel("wss://echo.websocket.org")
    
    # Setup handlers
    channel.on_open(lambda: print("Connected!"))
    channel.on_message(lambda msg: print(f"Received: {msg}"))
    channel.on_error(lambda err: print(f"Error: {err}"))
    
    # Connect and send
    await channel.connect()
    await channel.send("Hello, World!")
    await channel.send({"type": "test", "data": "JSON message"})
    
    # Wait a bit to receive echo
    await asyncio.sleep(2)
    
    await channel.close()

asyncio.run(test())
```

## Examples

See the `examples/` directory for complete working examples:
- Basic channel usage
- Component integration
- Room management
- Real-time chat application

