"""
Component ref utilities for exposing methods and variables from child to parent components.
Provides a simple API similar to SolidJS refs.
"""
from typing import Any, Dict, Callable, Optional, Union
from js import console


class ComponentRef:
    """
    A wrapper around a ref object that provides a simple API for exposing
    methods and variables from child components to parent components.
    
    Usage in child component:
        ref = use_ref(props)
        ref.expose("handle_submit", handle_submit_function)
        ref.expose("some_var", some_value)
    
    Usage in parent component:
        form_ref = {}
        <ChildComponent ref:=form_ref />
        form_ref.handle_submit()  # Call exposed method
        value = form_ref.some_var  # Access exposed variable
    """
    
    def __init__(self, ref_obj: Any):
        """
        Initialize a ComponentRef with a ref object.
        
        Args:
            ref_obj: The ref object passed from parent (dict or Proxy)
        """
        self._ref = ref_obj
        self._initialized = ref_obj is not None
        
    def expose(self, name_or_value: Union[str, Callable, Any], value: Optional[Any] = None) -> None:
        """
        Expose a method or variable to the parent component.
        
        Can be called in two ways:
        1. expose(function) - Uses the function's name as the key
        2. expose(name, value) - Explicitly sets the name and value
        
        Args:
            name_or_value: If callable and value is None, uses function name as key.
                          Otherwise, this is the name (str) to expose.
            value: The function or value to expose. If None and name_or_value is callable,
                   uses name_or_value's name as the key.
        """
        if not self._initialized:
            console.warn(f"ComponentRef.expose: Not initialized, cannot expose")
            return
        
        # Determine the actual name and value
        if value is None and callable(name_or_value):
            # Called as expose(function) - use function name as key
            actual_name = getattr(name_or_value, '__name__', 'anonymous')
            actual_value = name_or_value
        elif isinstance(name_or_value, str) and value is not None:
            # Called as expose(name, value) - explicit name and value
            actual_name = name_or_value
            actual_value = value
        elif callable(name_or_value):
            # Fallback: treat as function without explicit name
            actual_name = getattr(name_or_value, '__name__', 'anonymous')
            actual_value = name_or_value
        else:
            # Non-callable without explicit name - raise error
            raise ValueError("expose() requires either a callable or (name, value) pair")
            
        try:
            # Check if it's a RefHolder - use its built-in expose method
            from metafor.core import RefHolder
            if isinstance(self._ref, RefHolder):
                self._ref.expose(actual_name, actual_value)
                return
            
            # Check if it's a Pyodide Proxy and try to get the underlying object
            from pyodide.ffi import JsProxy
            ref_to_use = self._ref
            
            # If it's a JsProxy, try to access the underlying Python object
            if isinstance(self._ref, JsProxy):
                # Try to get the underlying dict if it's a proxy of a dict
                try:
                    # Check if it has a to_py method (Pyodide 0.24+)
                    if hasattr(self._ref, 'to_py'):
                        ref_to_use = self._ref.to_py()
                except:
                    pass
            
            # Try dict assignment first
            if isinstance(ref_to_use, dict):
                ref_to_use[actual_name] = actual_value
                return
            
            # Check if it's a RefHolder-like object (has _data attribute)
            if hasattr(ref_to_use, '_data') and isinstance(getattr(ref_to_use, '_data', None), dict):
                ref_to_use._data[actual_name] = actual_value
                # Also try setting as attribute for RefHolder
                try:
                    setattr(ref_to_use, actual_name, actual_value)
                except:
                    pass
                return
            
            # For other types, try multiple methods
            # Method 1: Direct attribute assignment (works for most Python objects)
            try:
                setattr(ref_to_use, actual_name, actual_value)
                # Verify it was set
                if hasattr(ref_to_use, actual_name):
                    return
                else:
                    console.warn(f"ComponentRef.expose: setattr succeeded but attribute not found")
            except Exception as e1:
                console.error(f"ComponentRef.expose: setattr failed for '{actual_name}':", e1)
            
            # Method 2: __setitem__ (works for dict-like objects)
            if hasattr(ref_to_use, '__setitem__'):
                try:
                    ref_to_use[actual_name] = actual_value
                    # Verify it was set
                    try:
                        test_val = ref_to_use[actual_name]
                        if test_val == actual_value:
                            return
                    except:
                        pass
                    console.warn(f"ComponentRef.expose: Exposed '{actual_name}' via __setitem__")
                except Exception as e2:
                    console.error(f"ComponentRef.expose: __setitem__ failed for '{actual_name}':", e2)
            
            # Method 3: Try setting on the original ref if it's different
            if ref_to_use is not self._ref:
                try:
                    setattr(self._ref, actual_name, actual_value)
                except:
                    pass
                    
        except Exception as e:
            console.error(f"Error exposing '{actual_name}' to ref:", e, "ref type:", type(self._ref))
    


# use_ref has been moved to metafor.hooks
# Import it from there: from metafor.hooks import use_ref

