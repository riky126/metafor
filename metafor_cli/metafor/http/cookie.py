from js import console, document
from typing import Dict, Any, Optional
import time

class CookieManager:
    """A manager for handling cookies in the HTTP client."""

    def __init__(self):
        self.cookies = {}

    def set_cookie(self, name: str, value: str, options: Dict[str, Any] = None):
        """Set a cookie by name and value with optional attributes."""
        options = options or {}
        self.cookies[name] = {
            'value': value,
            'options': options
        }

        # Also set in document.cookie for browser persistence
        cookie_str = f"{name}={value}"
        if options:
            if options.get('path'):
                cookie_str += f"; path={options['path']}"
            if options.get('domain'):
                cookie_str += f"; domain={options['domain']}"
            if options.get('expires'):
                if isinstance(options['expires'], str):
                    cookie_str += f"; expires={options['expires']}"
                elif isinstance(options['expires'], (int, float)):
                    expires_time = time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime(options['expires']))
                    cookie_str += f"; expires={expires_time}"
            if options.get('max-age'):
                cookie_str += f"; max-age={options['max-age']}"
            if options.get('secure'):
                cookie_str += "; secure"
            if options.get('samesite'):
                cookie_str += f"; samesite={options['samesite']}"

        try:
            document.cookie = cookie_str
        except:
            console.warn("Unable to set document.cookie. Running in an environment without DOM access?")

    def get_cookie(self, name: str) -> Optional[str]:
        """Get a cookie value by name."""
        if name in self.cookies:
            # Check if the cookie has expired
            if self._is_cookie_expired(self.cookies[name]['options']):
                del self.cookies[name]
                return None
            return self.cookies[name]['value']

        # Try to get from document.cookie as fallback
        try:
            cookies = document.cookie.split(';')
            for cookie in cookies:
                parts = cookie.strip().split('=')
                if len(parts) >= 2 and parts[0] == name:
                    return parts[1]
        except:
            pass

        return None

    def remove_cookie(self, name: str, options: Dict[str, Any] = None):
        """Remove a cookie by name."""
        if name in self.cookies:
            del self.cookies[name]

        # Also remove from document.cookie
        try:
            # Set expiration to past date to remove the cookie
            cookie_str = f"{name}=; expires=Thu, 01 Jan 1970 00:00:00 GMT"
            if options:
                if options.get('path'):
                    cookie_str += f"; path={options['path']}"
                if options.get('domain'):
                    cookie_str += f"; domain={options['domain']}"
            document.cookie = cookie_str
        except:
            console.warn("Unable to remove from document.cookie. Running in an environment without DOM access?")

    def get_all_cookies(self) -> Dict[str, str]:
        """Get all cookies as a dictionary of name:value pairs."""
        result = {}
        for name, data in self.cookies.items():
            # Check if the cookie has expired
            if not self._is_cookie_expired(data['options']):
                result[name] = data['value']

        # Also try to get from document.cookie
        try:
            cookies = document.cookie.split(';')
            for cookie in cookies:
                parts = cookie.strip().split('=')
                if len(parts) >= 2:
                    result[parts[0]] = parts[1]
        except:
            pass

        return result

    def clear_all_cookies(self):
        """Clear all cookies."""
        self.cookies = {}

        # Clear document.cookie
        try:
            cookies = document.cookie.split(';')
            for cookie in cookies:
                parts = cookie.strip().split('=')
                if len(parts) >= 1:
                    document.cookie = f"{parts[0]}=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/"
        except:
            console.warn("Unable to clear document.cookie. Running in an environment without DOM access?")

    def get_cookie_header(self) -> Optional[str]:
        """Get the Cookie header value for all cookies."""
        all_cookies = self.get_all_cookies()
        if not all_cookies:
            return None

        cookie_parts = [f"{name}={value}" for name, value in all_cookies.items()]
        return "; ".join(cookie_parts)

    def _is_cookie_expired(self, options: Dict[str, Any]) -> bool:
        """Check if a cookie has expired based on its options."""
        if 'expires' in options:
            if isinstance(options['expires'], (int, float)):
                return time.time() > options['expires']
        if 'max-age' in options:
            max_age = int(options['max-age'])
            creation_time = options.get('creation_time', time.time())
            return time.time() > creation_time + max_age
        return False
