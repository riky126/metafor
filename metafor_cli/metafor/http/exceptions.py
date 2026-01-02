class HttpError(Exception):
    """Exception raised for HTTP errors (4xx and 5xx status codes)"""

    def __init__(self, error_data):
        self.message = error_data.get("message", "HTTP Error")
        self.response = error_data.get("response")
        self.config = error_data.get("config")
        self.phase = error_data.get("phase", "unknown")
        self.original_error = error_data.get("original_error")
        super().__init__(self.message)

class RequestCancelledError(HttpError):
    pass

class RetryRequestError(Exception):
    pass