from js import console, AbortController
from typing import Callable,List


class ProgressTracker:
    """Tracks upload and download progress for HTTP requests."""

    def __init__(self, total_size: int = 0):
        self.total_size = total_size
        self.loaded_size = 0
        self.progress_callbacks = []

    def update(self, chunk_size: int):
        """Update the loaded size and call progress callbacks."""
        self.loaded_size += chunk_size
        progress = {
            'loaded': self.loaded_size,
            'total': self.total_size,
            'percent': (self.loaded_size / self.total_size * 100) if self.total_size > 0 else 0
        }

        for callback in self.progress_callbacks:
            try:
                callback(progress)
            except Exception as e:
                console.error(f"Error in progress callback: {str(e)}")

    def add_callback(self, callback: Callable):
        """Add a progress callback function."""
        if callable(callback):
            self.progress_callbacks.append(callback)

    def remove_callback(self, callback: Callable):
        """Remove a progress callback function."""
        if callback in self.progress_callbacks:
            self.progress_callbacks.remove(callback)

class CancellationToken:
    """Token for cancelling HTTP requests."""

    def __init__(self):
        self.abort_controller = AbortController.new()
        self.cancelled = False

    def cancel(self):
        """Cancel the request."""
        if not self.cancelled:
            self.abort_controller.abort()
            self.cancelled = True

    def get_signal(self):
        """Get the AbortSignal for fetch."""
        return self.abort_controller.signal

    @property
    def is_cancelled(self):
        """Check if the request has been cancelled."""
        return self.cancelled

class RetryConfig:
    """Configuration for request retry behavior."""

    def __init__(self,
                 retries: int = 2,
                 retry_delay: int = 1000,
                 exponential_backoff: bool = True,
                 retry_status_codes: List[int] = None,
                 retry_methods: List[str] = None,
                 on_retry: Callable = None):
        """
        Initialize retry configuration.

        Args:
            retries: Maximum number of retry attempts
            retry_delay: Base delay between retries in milliseconds
            exponential_backoff: Whether to use exponential backoff for delays
            retry_status_codes: HTTP status codes that trigger a retry
            retry_methods: HTTP methods that can be retried
            on_retry: Callback function called before each retry attempt
        """
        self.retries = retries
        self.retry_delay = retry_delay
        self.exponential_backoff = exponential_backoff
        self.retry_status_codes = retry_status_codes or [408, 429, 500, 502, 503, 504]
        self.retry_methods = retry_methods or ["GET", "HEAD", "OPTIONS"]
        self.on_retry = on_retry

    def should_retry(self, status_code: int, method: str, attempt: int) -> bool:
        """
        Determine if a request should be retried.

        Args:
            status_code: The HTTP status code of the failed request
            method: The HTTP method used
            attempt: The current attempt number (0-based)

        Returns:
            Boolean indicating whether to retry
        """
        return (
                attempt < self.retries and
                method.upper() in [m.upper() for m in self.retry_methods] and
                status_code in self.retry_status_codes
        )

    def get_delay(self, attempt: int) -> int:
        """
        Calculate the delay before the next retry.

        Args:
            attempt: The current attempt number (0-based)

        Returns:
            Delay in milliseconds
        """
        if self.exponential_backoff:
            # Exponential backoff with jitter
            delay = self.retry_delay * (2 ** attempt)
            # Add jitter (±20%)
            jitter = delay * 0.2
            import random
            delay += random.uniform(-jitter, jitter)
            return max(0, int(delay))
        else:
            return self.retry_delay
