from js import console
from pyodide.ffi import JsProxy

# key generation utility
def generate_key(item, id_attr='id'):
    """
    Generate a key based on an object's ID attribute or string representation

    Args:
        item: The item to generate a key for
        id_attr (str, optional): Attribute to use for key generation. Defaults to 'id'

    Returns:
        A unique identifier for the item
    """
    if hasattr(item, id_attr):
        return getattr(item, id_attr)
    elif hasattr(item, '__hash__'):
        return hash(item)
    else:
        return str(item)
    

def is_safely_callable(obj):
    if not callable(obj):
        return False
    if isinstance(obj, JsProxy):
        try:
            if hasattr(obj, "nodeType") or hasattr(obj, "tagName"):
                console.log("Found DOM node being treated as callable")
                return False
            return callable(obj) and (hasattr(obj, "call") or hasattr(obj, "apply"))
        except Exception as e:
            console.error("Error checking JsProxy:", e)
            return False
    return True