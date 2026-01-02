class ChannelError(Exception):
    """Base exception for channel-related errors."""
    pass

class ChannelConnectionError(ChannelError):
    """Exception raised when channel connection fails."""
    pass

class ChannelMessageError(ChannelError):
    """Exception raised when sending/receiving messages fails."""
    pass

