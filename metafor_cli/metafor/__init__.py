from .core import render, RefHolder, create_ref
from js import document

__version__ = "0.1.0-beta"

get_version = lambda: __version__


def mount(Component, target_element, context=None):
    """
    Mount a component to a target element
    """
    app_container = document.getElementById(target_element)
    
    if not app_container:
        raise Exception(f"Element with id '{target_element}' not found.")

    # Initialize the application
    app = render(Component, target_element)
    return app