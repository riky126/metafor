import html
import re
from js import console

def preserve_whitespace(text):
    if not text: return text
    # Don't touch pure whitespace (indentation)
    if not text.strip():
        return text
        
    # Unescape HTML entities (e.g. &nbsp; -> \u00A0)
    text = html.unescape(text)
        
    if text.startswith(" ") and not text.startswith("\n"):
        text = "\u00A0" + text[1:]
    if text.endswith(" ") and not text.endswith("\n"):
        text = text[:-1] + "\u00A0"
    return text


def html_sanitize(html_string: str) -> str:
    """
    Performs HTML sanitization by removing potentially dangerous tags and attributes.
    
    Args:
        html_string: The HTML string to sanitize.
    """
    if not isinstance(html_string, str):
        try:
            html_string = str(html_string)
        except Exception:
            console.warn("html_sanitize: Input could not be converted to string. Returning empty string.")
            return ""
    
    # 1. Remove <script> tags and their content
    clean_html = re.sub(r'<script.*?>.*?</script>', '', html_string, flags=re.IGNORECASE | re.DOTALL)
    
    # 2. Remove common inline event handlers (on* attributes)
    clean_html = re.sub(r'\s+on\w+\s*=\s*("[^"]*"|\'[^\']*\'|[^\s>]+)', '', clean_html, flags=re.IGNORECASE)
    
    # 3. Remove javascript: links
    clean_html = re.sub(r'href\s*=\s*("|\')?\s*javascript:[^"\'>\s]+("|\')?', 'href="javascript:void(0)"', clean_html, flags=re.IGNORECASE)
    
    # 4. Remove potentially dangerous tags
    dangerous_tags = ['iframe', 'object', 'embed', 'form', 'base', 'link', 'meta']
    for tag in dangerous_tags:
        pattern = f'<{tag}.*?>.*?</{tag}>|<{tag}.*?/?>'
        clean_html = re.sub(pattern, '', clean_html, flags=re.IGNORECASE | re.DOTALL)
    
    # 5. Remove data: URLs (often used for XSS)
    clean_html = re.sub(r'(src|href)\s*=\s*("|\')?\s*data:[^"\'>\s]+("|\')?', r'\1="javascript:void(0)"', clean_html, flags=re.IGNORECASE)
    
    # 6. Sanitize style attributes to prevent CSS-based attacks
    clean_html = re.sub(r'style\s*=\s*("|\').*?(expression|javascript|behavior|eval|vbscript).*?("|\')', 'style=""', clean_html, flags=re.IGNORECASE)
    
    return clean_html