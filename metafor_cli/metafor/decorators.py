from enum import Enum
from functools import wraps
import uuid
from typing import Dict, Any, Callable, get_args, Union, Optional
from types import FunctionType

from metafor.core import _effects, _current_effect, track, untrack

class BaseType(Enum):
    Page = 'Page'
    Component = 'Component'

def component(props: Dict[str, Any] = None, **other_kwargs):
    """
    Decorator to mark a function as a component.

    Args:
        component_func: The function to be decorated.
        props: A dictionary specifying the expected props and their types.
    """
    def decorator(component_func):

        # Add attributes directly to the component_func
        component_func.__id__ = str(uuid.uuid4())
        component_func.__tag__ = other_kwargs.get('tag', 'div')
        component_func.__type__ = BaseType.Component.value
        component_func.__props__ = props or {}  # Store prop definitions
        component_func.__effects__ = _effects[_current_effect] if _current_effect else None

        @wraps(component_func)
        def create_instance(*args, **kwargs):
            # Validate props if defined
            if component_func.__props__:
                _validate_props(kwargs, component_func.__props__)

            # Wrap ref with ComponentRef if it exists and isn't already wrapped
            if 'ref' in kwargs and kwargs['ref'] is not None:
                from metafor.utils.ref import ComponentRef
                if not isinstance(kwargs['ref'], ComponentRef):
                    kwargs['ref'] = ComponentRef(kwargs['ref'])

            # Create a new copy of the function with its own ID
            @wraps(component_func)
            def new_instance(**inner_kwargs):
                return component_func(**inner_kwargs)

            new_instance.__id__ = component_func.__id__
            new_instance.__tag__ = component_func.__tag__
            new_instance.__type__ = component_func.__type__
            new_instance.__props__ = component_func.__props__
            new_instance.__effects__ = component_func.__effects__
        
            if 'children' not in kwargs:
                kwargs['children'] = None
            
            return new_instance(**kwargs)

        return create_instance
    
    return decorator


def page(path:str, props: Dict[str, Any] = None, **other_kwargs):
    """
    Decorator to mark a function as a page component.

    Args:
        component_func: The function to be decorated.
        props: A dictionary specifying the expected props and their types.
    """
    
    def decorator(component_func):
        
        @component(props=props, **other_kwargs)  # Apply the component decorator with props
        @wraps(component_func)
        def page_instance(*args, **kwargs):
            # Get a new instance
            return component_func(*args, **kwargs)

        page_instance.__type__ = BaseType.Page.value
        page_instance.__path__ = path

        return page_instance
    
    return decorator


def reusable(func):
    """
    Decorator to mark a function as a reusable.

    Args:
        func: The function to be decorated.
    """

    @wraps(func)
    def decorator(*args, **kwargs):
        props = {
            **kwargs,
            "track": track,
            "untrack": untrack,
        }
        return func(*args, **props)
    
    return decorator
        
        
def _validate_props(received_props: Dict[str, Any], expected_props: Dict[str, Any]):
    """
    Validates the received props against the expected prop definitions.

    Args:
        received_props: The props received by the component.
        expected_props: The expected prop definitions (name: type).

    Raises:
        TypeError: If a prop is of the wrong type.
        ValueError: If a required prop is missing.
    """
    for prop_name, prop_info in expected_props.items():
        prop_type = prop_info
        default_value = None
        is_optional = False

        if isinstance(prop_info, tuple):
            prop_type, default_value = prop_info
            # Check if the type inside the tuple is Optional
            if hasattr(prop_type, '__origin__') and prop_type.__origin__ is Union and type(None) in get_args(prop_type):
                is_optional = True
                prop_type = [t for t in get_args(prop_type) if t is not type(None)][0]
        elif hasattr(prop_info, '__origin__') and prop_info.__origin__ is Union and type(None) in get_args(prop_info):
            prop_type = [t for t in get_args(prop_info) if t is not type(None)][0]
            is_optional = True

        if prop_name not in received_props:
            if default_value is not None:
                received_props[prop_name] = default_value
            elif not is_optional:
                raise ValueError(f"Missing required prop: '{prop_name}'")
            continue
        
        # Check if the expected type is 'any' or if it's a Union with 'Any'
        if prop_type is not Any and not (hasattr(prop_type, '__origin__') and prop_type.__origin__ is Union and Any in get_args(prop_type)):
            if not isinstance(received_props[prop_name], prop_type):
                # Special handling for callable type
                if prop_type is callable or prop_type is FunctionType:
                    if callable(received_props[prop_name]):
                        continue
                raise TypeError(
                    f"Prop '{prop_name}' should be of type '{prop_type.__name__}', "
                    f"but received '{type(received_props[prop_name]).__name__}'"
                )
