# Metafor Channels Usage Guide

The `metafor/channels` library provides a Pythonic wrapper for WebSocket communication, leveraging native browser WebSockets via Pyodide. It simplifies connection management, event handling, and real-time messaging, including support for Phoenix Channels-style "rooms".

## Table of Contents
1. [Basic Usage](#basic-usage)
2. [Connection Management](#connection-management)
3. [Sending Messages](#sending-messages)
4. [Event Handling](#event-handling)
5. [Room / Topic Support](#room--topic-support)

---

## Basic Usage

Connect to a WebSocket server and listen for messages.

```python
from metafor.channels.channel import Channel

# 1. Initialize
channel = Channel("wss://api.example.com/socket")

# 2. Register Handlers
channel.on_open(lambda e: print("Connected!"))
channel.on_message(lambda msg: print("Received:", msg))

# 3. Connect
channel.connect()

# 4. Send Message
channel.send({"type": "greeting", "text": "Hello World"})
```

## Connection Management

The `Channel` class handles connection states and optional auto-reconnection.

```python
channel = Channel(
    "wss://api.example.com/socket",
    auto_reconnect=True,
    reconnect_delay=2.0
)

channel.connect()

# Check state
if channel.is_connected():
    print("Online")

# Disconnect
channel.close()
```

## Sending Messages

Send text, binary, or JSON data.

```python
# Send text
channel.send("Hello")

# Send JSON (automatically serialized)
channel.send({"action": "update", "id": 123})

# Send Binary (bytes)
channel.send(b'\x00\x01')
```

## Event Handling

Register callbacks for various lifecycle events.

```python
# Connection established
channel.on_open(lambda e: print("Socket Open"))

# Connection closed
def on_close(event):
    print(f"Closed. Code: {event.code}, Reason: {event.reason}")
channel.on_close(on_close)

# Error occurred
channel.on_error(lambda e: print("Error:", e))

# Message received
channel.on_message(lambda msg: print("New Message:", msg))
```

## Room / Topic Support

The library supports a pattern for sending messages to specific "rooms" or "topics" (often used with backends like Phoenix Channels).

```python
# Send to a specific room
channel.send_to("room:lobby", {"text": "Hello everyone!"})

# Or using the send method with room argument
channel.send({"text": "Private msg"}, room="user:123")
```
*Note: This assumes the server expects a message format compatible with this routing logic.*
