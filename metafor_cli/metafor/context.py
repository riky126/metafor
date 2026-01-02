# /Users/ricardo/Documents/Development/metafor/metafor/context.py
import uuid
import weakref
from js import console
from metafor.decorators import component
from metafor.hooks import create_signal
from metafor.core import get_current_effect, _effects, Signal, create_effect

class Context:
    def __init__(self, initial_value=None):
        self.id = str(uuid.uuid4())
        self._signal, self._set_signal = create_signal(initial_value)
        self._listeners = weakref.WeakKeyDictionary()  # Component IDs to update functions
        self.initial_value = initial_value

    def get_value(self):
        """Gets the current value of the context."""
        # This returns the signal's value while preserving reactivity
        return self._signal()

    def set_value(self, new_value):
        """Sets the value of the context and notifies listeners."""
        # Update the signal - this should trigger reactive updates
        self._set_signal(new_value)
        # Also manually notify listeners
        self.notify()

    def subscribe(self, effect, update_fn):
        """Subscribes a component to context updates."""
        self._listeners[effect] = update_fn

    def unsubscribe(self, effect):
        """Unsubscribes a component from context updates."""
        if effect in self._listeners:
            del self._listeners[effect]

    def notify(self):
        """Notifies all subscribed components of a context update."""
        # Use a copy of the listeners to avoid modification during iteration
        for effect, update_fn in list(self._listeners.items()):
            try:
                update_fn()
            except Exception as e:
                console.error(f"Error notifying component {effect} :", e)

    def __call__(self, value=None):
        """Allows setting/getting value using function call syntax."""
        if value is not None:
            self.set_value(value)
        return self.get_value()

@component()
def ContextProviderProxy():
    return None

class ContextProvider:
    def __init__(self, context, value, children):
        self.context = context
        self._value = value if isinstance(value, Signal) else create_signal(value)[0] # if value is not a signal, create a signal
        self.children = children
        self._effect = get_current_effect()
        self._cleanup_list = []
        # Set the context value immediately during initialization 
        # This is important because we want the value to be available
        # before any child components try to use it
        self.context.set_value(self._value())
        
        #create effect to update the context
        create_effect(self.update_context_value)

        def on_dispose_callback():
            # Clean up when the component is disposed
            for cleanup in self._cleanup_list:
                try:
                    cleanup()
                except Exception as e:
                    console.error(
                        "Error running cleanup function in on_dispose_callback", e
                    )

            self.context.unsubscribe(self._effect)

        self.on_dispose_callback = on_dispose_callback

    def component_will_unmount(self):
        """Cleans up the context when the component unmounts."""
        self.on_dispose_callback()
    
    def update_context_value(self):
        """Update the context value from the signal."""
        self.context.set_value(self._value())

    def render(self):
        """Renders the children within the context."""
        rendered_children = None
        
        if callable(self.children):
            rendered_children = self.children()
        else:
            rendered_children = self.children

        if self._effect in _effects:
            # Register dispose callback
            _effects[self._effect]["disposals"].append(self.on_dispose_callback)

        return rendered_children

    def __call__(self):
        """Renders the context provider."""
        # Don't call update_context_value here, as it's already set in __init__
        # Only use update_context_value when the provider's value changes
        return self.render()
    
    def set_value(self, new_value):
        """Update the provider value."""
        self._value.set(new_value)

