import asyncio
from typing import Any, Callable, Tuple, Dict, Optional
from js import console
from inspect import isawaitable
from metafor.core import (
    Memo, 
    Signal,
    LinkedSignal,
    _effects,
    batch_updates, 
    create_effect, 
    create_signal,
    get_current_effect, 
    on_dispose, suspend_tracking)

from metafor.store import Provider, ProviderContainer
from metafor.utils.ref import ComponentRef

def create_memo(compute_fn: Callable[[], Any]) -> Signal:
    """Create a memoized signal that recomputes only when dependencies change"""
    memo = Memo(compute_fn)
    return memo

def create_derived(*sources, compute_fn: Callable = None) -> LinkedSignal:
    """
    Create a linked signal from one or more source signals and a compute function.
    Works like Angular's LinkedSignal: manual updates persist until source signals change.
    
    Args:
        *sources: One or more source signals to derive from, or a single list/tuple of signals
        compute_fn: Function that takes the source values as separate arguments and returns the computed value.
                   Can be passed as keyword argument or as second positional argument when sources is a list.
    
    Returns:
        A LinkedSignal that derives its value from the source signals.
        Also returns a setter function: (linked_signal, set_linked_signal)
    
    Examples:
        # Multiple sources as arguments
        derived, set_derived = create_derived(source1, source2, compute_fn=lambda x, y: x + y)
        
        # Single list of sources with keyword compute_fn
        derived, set_derived = create_derived([source1, source2], compute_fn=lambda x, y: x + y)
        
        # Single list of sources with positional compute_fn
        derived, set_derived = create_derived([source1, source2], lambda x, y: x + y)
        
        # Single source with positional compute_fn
        derived, set_derived = create_derived(source1, lambda x: x * 2)
    """
    # Handle case: create_derived([source1, source2], lambda ...)
    # When first arg is a list/tuple and compute_fn is None, check if second arg is the compute_fn
    if len(sources) == 2 and isinstance(sources[0], (list, tuple)) and compute_fn is None:
        if callable(sources[1]):
            # Extract compute_fn from original sources before unpacking
            compute_fn = sources[1]
            # Unpack the list
            sources = tuple(sources[0])
        else:
            raise ValueError("Second argument must be a callable compute function")
    # Handle case: create_derived([source1, source2], compute_fn=...)
    elif len(sources) == 1 and isinstance(sources[0], (list, tuple)):
        sources = tuple(sources[0])
    # Handle case: create_derived(source1, lambda ...) or create_derived(source1, source2, lambda ...)
    # When compute_fn is None and last argument is callable (and not a Signal), treat it as compute_fn
    elif len(sources) >= 2 and compute_fn is None:
        # Check if last argument is callable and not a Signal/Memo
        last_arg = sources[-1]
        if callable(last_arg) and not isinstance(last_arg, (Signal, Memo)):
            # Last argument is the compute_fn, rest are sources
            compute_fn = last_arg
            sources = sources[:-1]
    
    if compute_fn is None:
        raise ValueError("compute_fn must be provided")
    
    # Validate that each source is a Signal, Memo, or LinkedSignal instance
    # Note: LinkedSignal is a subclass of Signal, so isinstance check covers it
    for i, source in enumerate(sources):
        if not isinstance(source, (Signal, Memo)):
            raise TypeError(f"Source at index {i} must be a Signal, Memo, or LinkedSignal instance, got {type(source).__name__}")
    
    linked_signal = LinkedSignal(*sources, compute_fn=compute_fn)
    return linked_signal, linked_signal.set
    

# use_context hook
def use_context(context):
    """
    Custom hook to access the value from a context and react to changes
    without causing component recreation.
    """
    effect_ref = get_current_effect() 
    # if not effect_ref.__type__ :
    #     raise Exception('You can use on_mount outside of a component')
   
    # This leverages the reactivity of the context's internal signal
    value = context.get_value
    
    # Register cleanup for when component unmounts
    def cleanup():
        context.unsubscribe(effect_ref)

    # Make sure cleanup is registered
    _effects[effect_ref].get("disposals").append(cleanup)
    
    # Return the context's signal function directly
    return value

def create_resource(source, fetcher):
    """
    Creates a resource that fetches data asynchronously.

    Args:
        source (callable or any): The dependency source for refetching. 
                                    If callable, it should return a value.
        fetcher (callable): The function that fetches the data.
                            It receives the source value as an argument.
                            Can be async or sync.

    Returns:
        tuple: A tuple containing:
            - read: A function to read the resource's value.
            - state: a signal that return the state of the resource. 'pending', 'ready', 'error'
    """
    
    resource_signal, set_resource_signal = create_signal(None)
    state_signal, set_state_signal = create_signal('pending')

    async def update_resource():
        set_state_signal('pending')
        current_source = source() if callable(source) else source
        try:
            result = fetcher(current_source)
            if isawaitable(result):
                result = await result
            
            batch_updates(lambda: [
                set_resource_signal(result),
                set_state_signal('ready')
            ])

        except Exception as e:
            console.error(f"Error fetching resource: {e}")
            set_resource_signal(e)
            set_state_signal('error')

    def read():
        if state_signal() == 'pending':
            raise Exception("Resource is still loading")
        elif state_signal() == 'error':
            raise resource_signal()
        return resource_signal()

    def execute():
        if callable(source):
            create_effect(update_resource)
        else:
            asyncio.create_task(update_resource())

    execute()
    
    return read, state_signal, execute



def use_provider(container: ProviderContainer, provider: Provider) -> tuple[Any, Callable[[Any], None]]:
    """
    A utility hook to access and watch a provider's state from a StateContainer.

    Args:
        container: The StateContainer instance.
        provider: The provider instance.

    Returns:
        A tuple containing:
        - The initial value of the provider's state.
        - A setter function to update the provider's state.
    """
    
    # Get the initial value of the provider
    initial_value = container.get(provider)
    # Create a signal to hold the current value
    value_signal, set_value_signal = create_signal(initial_value)

    def provider_listener(new_value):
        """
        Listener function that's triggered when the provider's state changes.
        It updates the signal with the new value.
        """
        set_value_signal(new_value)

    unsubscribe = container.watch(provider, provider_listener)

    # Register a cleanup function to unsubscribe from the provider when the component unmounts
    def cleanup():
        unsubscribe()
    
    on_dispose(cleanup)

    return value_signal, lambda new_value: container.set(provider, new_value)


def use_beanstack_store(store: Any, slice_key: str=None) -> tuple[Any, Callable[[Any], None]]:
    """
    A utility hook to access and subscribe to a beanstack state.

    Args:
        store: The Beanstack instance.
        slice_key: A State slice.

    Returns:
        A tuple containing:
        - The state or slice of the store.
        - A dispatch function to update the store.
    """
    
    state, set_value_signal = create_signal(store.get_state(slice_key))

    def state_listener():
        set_value_signal(store.get_state(slice_key))

    unsubscribe =  store.subscribe(state_listener)

    def cleanup():
        unsubscribe()
    
    on_dispose(cleanup)

    return state, store.dispatch


def use_ref(props: Dict[str, Any]) -> Optional[ComponentRef]:
    """
    Hook to get a ComponentRef from component props.
    
    Usage in child component:
        ref = use_ref(props)
        if ref:
            ref.expose("handle_submit", handle_submit_function)
    
    Args:
        props: The component's props dictionary
        
    Returns:
        ComponentRef instance if ref prop exists, None otherwise
    """
    parent_ref = props.get("ref")
    if parent_ref:
        # Debug logging
        console.log("use_ref: Found ref in props:", parent_ref, "type:", type(parent_ref))
        return ComponentRef(parent_ref)
    else:
        # Debug logging
        console.log("use_ref: No ref found in props. Props keys:", list(props.keys()) if hasattr(props, 'keys') else "N/A")
    return None

