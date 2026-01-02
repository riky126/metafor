import asyncio
import inspect
from collections import defaultdict
from typing import Callable, Any, Dict, List, Set, TypeVar, Generic, Union
from functools import wraps

T = TypeVar('T')
R = TypeVar('R')

class ProviderError(Exception):
    """Base exception for provider-related errors."""
    pass

class ProviderNotFoundError(ProviderError):
    """Exception raised when a provider is not found."""
    def __init__(self, provider_key):
        super().__init__(f"Provider '{provider_key}' not found.")

class CircularDependencyError(ProviderError):
    """Exception raised when circular dependencies are detected."""
    def __init__(self, dependency_path):
        path_str = " -> ".join(str(p) for p in dependency_path)
        super().__init__(f"Circular dependency detected: {path_str}")

class _ProviderContainer:
    """
    Internal container to hold and manage provider states.
    """
    def __init__(self):
        self._providers: Dict[Any, Any] = {}
        self._providers_metadata: Dict[Any, Dict] = {}
        self._listeners: Dict[Any, List[Callable]] = defaultdict(list)
        self._initialization_stack: List[Any] = []

    def get_provider_state(self, provider_key):
        """Retrieves the state of a provider."""
        if provider_key not in self._providers:
            raise ProviderNotFoundError(provider_key)
        return self._providers[provider_key]
    
    def set_provider_state(self, provider_key, new_value):
        """Sets the state of a provider and notifies listeners."""
        if provider_key not in self._providers:
            raise ProviderNotFoundError(provider_key)
        
        previous_value = self._providers[provider_key]
        self._providers[provider_key] = new_value
        
        # Only notify if the value has actually changed
        if previous_value != new_value:
            self._notify_listeners(provider_key, previous_value, new_value)

    def get_provider_metadata(self, provider_key, key=None, default=None):
        """Retrieves metadata for a provider."""
        if provider_key not in self._providers_metadata:
            self._providers_metadata[provider_key] = {}
        
        if key is not None:
            return self._providers_metadata[provider_key].get(key, default)
        return self._providers_metadata[provider_key]
    
    def set_provider_metadata(self, provider_key, key, value):
        """Sets metadata for a provider."""
        if provider_key not in self._providers_metadata:
            self._providers_metadata[provider_key] = {}
        
        self._providers_metadata[provider_key][key] = value
    
    def create_provider_state(self, provider_key, creator_function, dependencies=None):
        """
        Create the provider state, checking for circular dependencies.
        """
        # Check for circular dependencies
        if provider_key in self._initialization_stack:
            # Found a circular dependency
            cycle_index = self._initialization_stack.index(provider_key)
            dependency_path = self._initialization_stack[cycle_index:] + [provider_key]
            raise CircularDependencyError(dependency_path)
        
        # Add to initialization stack to track dependency chains
        self._initialization_stack.append(provider_key)
        
        try:
            # Create the provider state
            self._providers[provider_key] = creator_function()
            
            # Store dependency information
            if dependencies:
                self.set_provider_metadata(provider_key, 'dependencies', dependencies)
                
                # Add this provider as a dependent to each dependency
                for dep in dependencies:
                    dependents = self.get_provider_metadata(dep, 'dependents', set())
                    dependents.add(provider_key)
                    self.set_provider_metadata(dep, 'dependents', dependents)
        finally:
            # Remove from initialization stack
            self._initialization_stack.pop()

    def add_listener(self, provider_key, listener):
        """Adds a listener for a provider."""
        self._listeners[provider_key].append(listener)
        return listener

    def remove_listener(self, provider_key, listener):
        """Removes a listener for a provider."""
        if provider_key in self._listeners and listener in self._listeners[provider_key]:
            self._listeners[provider_key].remove(listener)
            return True
        return False

    def _notify_listeners(self, provider_key, previous_value, new_value):
        """
        Notifies all listeners of changes to a provider.
        Uses introspection to determine if listener accepts previous_value.
        """
        for listener in self._listeners[provider_key]:
            # Check the signature of the listener to see if it accepts two arguments
            try:
                sig = inspect.signature(listener)
                param_count = len(sig.parameters)
                
                if param_count >= 2:
                    # Listener accepts both new_value and previous_value
                    listener(new_value, previous_value)
                else:
                    # Backward compatibility: listener only accepts new_value
                    listener(new_value)
            except (ValueError, TypeError):
                # If we can't inspect the signature (e.g., for built-in functions),
                # try with just the new value for backward compatibility
                try:
                    listener(new_value)
                except TypeError:
                    # If that fails too, try with both arguments
                    listener(new_value, previous_value)

    def reset_provider(self, provider_key, creator_function=None):
        """Resets a provider to its initial state."""
        if provider_key not in self._providers:
            raise ProviderNotFoundError(provider_key)
            
        if creator_function:
            previous_value = self._providers[provider_key]
            self._providers[provider_key] = creator_function()
            self._notify_listeners(provider_key, previous_value, self._providers[provider_key])
        else:
            # Just notify that the provider was reset
            current_value = self._providers[provider_key]
            self._notify_listeners(provider_key, current_value, current_value)


class Provider(Generic[T]):
    """
    Base class for providers with generic typing support.
    """
    def __init__(self, name=None, dependencies=None):
        self.name = name if name else id(self)  # Unique identifier
        self.dependencies = dependencies or []

    def create(self, container: _ProviderContainer) -> T:
        """
        Must be implemented by subclasses.
        """
        raise NotImplementedError

    def get_state(self, container: _ProviderContainer) -> T:
        """
        Get state of the current provider.
        """
        return container.get_provider_state(self.name)
    
    def set_state(self, container: _ProviderContainer, new_value: T) -> None:
        """
        Set the value for the provider.
        """
        container.set_provider_state(self.name, new_value)

    def watch(self, container: _ProviderContainer, listener: Callable) -> Callable[[], bool]:
        """
        Registers a listener to be notified of state changes.
        Returns a function that can be called to remove the listener.
        
        The listener can accept one or two parameters:
        - new_value: The new state value
        - previous_value: (Optional) The previous state value
        """
        listener_ref = container.add_listener(self.name, listener)
        return lambda: container.remove_listener(self.name, listener_ref)
    
    def get_metadata(self, container: _ProviderContainer, key=None, default=None):
        """Gets metadata for this provider."""
        return container.get_provider_metadata(self.name, key, default)
    
    def set_metadata(self, container: _ProviderContainer, key, value):
        """Sets metadata for this provider."""
        container.set_provider_metadata(self.name, key, value)
    
    def reset(self, container: _ProviderContainer) -> None:
        """Resets the provider to its initial state."""
        container.reset_provider(self.name, lambda: self.create(container))
    
    def __call__(self, container: _ProviderContainer) -> T:
        """
        Call the provider to initialize its state.
        """
        if self.name not in container._providers:
            container.create_provider_state(
                self.name, 
                lambda: self.create(container),
                [dep.name if isinstance(dep, Provider) else dep for dep in self.dependencies]
            )
        return self.get_state(container)


class StateProvider(Provider[T]):
    """
    Provider that holds a simple state value.
    """
    def __init__(self, initial_state: T, name=None, dependencies=None):
        super().__init__(name=name, dependencies=dependencies)
        self.initial_state = initial_state

    def create(self, container: _ProviderContainer) -> T:
        return self.initial_state


class FutureProvider(Provider[T]):
    """
    Provider that resolves a future.
    """
    def __init__(self, future_factory: Callable[[_ProviderContainer], Union[T, asyncio.Future[T]]], 
                 name=None, dependencies=None):
        super().__init__(name=name, dependencies=dependencies)
        self.future_factory = future_factory
        self.future_result = None

    def create(self, container: _ProviderContainer) -> Union[T, asyncio.Future[T]]:
        """
        Create the future result and store it.
        """
        self.future_result = self.future_factory(container)
        return self.future_result

    async def wait(self, container: _ProviderContainer) -> T:
        """
        Waits for the Future to complete and returns its result.
        """
        if asyncio.iscoroutine(self.future_result):
            result = await self.future_result
            self.set_state(container, result)
            return result
        return self.future_result


class ComputedProvider(Provider[R]):
    """
    Provider that computes a value based on other providers.
    Will automatically update when dependencies change.
    """
    def __init__(self, 
                 compute_fn: Callable[..., R], 
                 dependencies: List[Provider], 
                 name=None):
        super().__init__(name=name, dependencies=dependencies)
        self.compute_fn = compute_fn
        self._cleanup_functions = []

    def create(self, container: _ProviderContainer) -> R:
        # Clean up any existing listeners
        self._cleanup_listeners()
        
        # Set up listeners for all dependencies
        for dep in self.dependencies:
            # Use adapter function to maintain backward compatibility
            def adapter(new_val, prev_val=None, dep=dep):
                self._recompute(container)
                
            cleanup = dep.watch(container, adapter)
            self._cleanup_functions.append(cleanup)
        
        # Compute initial value
        return self._compute_value(container)
    
    def _compute_value(self, container: _ProviderContainer) -> R:
        """Compute the value based on current dependency values."""
        dep_values = [dep(container) for dep in self.dependencies]
        return self.compute_fn(*dep_values)
    
    def _recompute(self, container: _ProviderContainer) -> None:
        """Recompute the value and update state."""
        new_value = self._compute_value(container)
        self.set_state(container, new_value)
    
    def _cleanup_listeners(self) -> None:
        """Clean up all dependency listeners."""
        for cleanup in self._cleanup_functions:
            cleanup()
        self._cleanup_functions = []


class FamilyProvider(Generic[T, R]):
    """
    Provider that creates a family of providers based on a parameter.
    """
    def __init__(self, factory: Callable[[T], Provider[R]], name_prefix=None):
        self.factory = factory
        self.name_prefix = name_prefix or id(self)
        self.instances: Dict[T, Provider[R]] = {}
    
    def get(self, param: T) -> Provider[R]:
        """
        Get or create a provider for the given parameter.
        """
        if param not in self.instances:
            provider = self.factory(param)
            
            # Override the name to ensure uniqueness within the family
            if isinstance(provider.name, str) and not provider.name.startswith(f"{self.name_prefix}_"):
                provider.name = f"{self.name_prefix}_{provider.name}"
            elif not isinstance(provider.name, str):
                provider.name = f"{self.name_prefix}_{param}"
                
            self.instances[param] = provider
        
        return self.instances[param]


class EffectProvider(Provider[None]):
    """
    Provider that runs side effects when dependencies change.
    Does not store a value itself.
    """
    def __init__(self, 
                 effect_fn: Callable[..., Any], 
                 dependencies: List[Provider], 
                 run_immediately: bool = True,
                 name=None):
        super().__init__(name=name, dependencies=dependencies)
        self.effect_fn = effect_fn
        self.run_immediately = run_immediately
        self._cleanup_functions = []
        self._dispose_fn = None

    def create(self, container: _ProviderContainer) -> None:
        # Clean up any existing listeners and effects
        self._cleanup()
        
        # Set up listeners for all dependencies
        for dep in self.dependencies:
            # Use adapter function to maintain backward compatibility
            def adapter(new_val, prev_val=None, dep=dep):
                self._run_effect(container)
                
            cleanup = dep.watch(container, adapter)
            self._cleanup_functions.append(cleanup)
        
        # Run the effect immediately if configured to do so
        if self.run_immediately:
            self._run_effect(container)
        
        return None
    
    def _run_effect(self, container: _ProviderContainer) -> None:
        """Run the effect function with current dependency values."""
        # Clean up previous effect if needed
        if callable(self._dispose_fn):
            self._dispose_fn()
            self._dispose_fn = None
        
        # Get current values of dependencies
        dep_values = [dep(container) for dep in self.dependencies]
        
        # Run the effect
        result = self.effect_fn(*dep_values)
        
        # Store the cleanup function if one was returned
        if callable(result):
            self._dispose_fn = result
    
    def _cleanup(self) -> None:
        """Clean up all listeners and the effect itself."""
        # Clean up dependency listeners
        for cleanup in self._cleanup_functions:
            cleanup()
        self._cleanup_functions = []
        
        # Clean up the effect
        if callable(self._dispose_fn):
            self._dispose_fn()
            self._dispose_fn = None
    
    def dispose(self, container: _ProviderContainer) -> None:
        """Explicitly dispose of the effect."""
        self._cleanup()


class ProviderContainer:
    """
    Main container for managing providers and their states.
    """
    def __init__(self):
        self._container = _ProviderContainer()

    def get(self, provider: Provider[T]) -> T:
        """
        Retrieves the state of a provider.
        """
        return provider(self._container)
    
    def set(self, provider: Provider[T], new_value: T) -> None:
        """
        Sets a value for the provider.
        """
        provider.set_state(self._container, new_value)

    def watch(self, provider: Provider[T], listener: Callable) -> Callable[[], bool]:
        """
        Registers a listener to be notified of state changes.
        Returns a function that can be called to remove the listener.
        
        The listener can accept one or two parameters:
        - new_value: The new state value
        - previous_value: (Optional) The previous state value
        """
        return provider.watch(self._container, listener)

    async def get_future(self, future_provider: FutureProvider[T]) -> T:
        """
        Waits for a FutureProvider to complete and returns its result.
        """
        return await future_provider.wait(self._container)
    
    def reset(self, provider: Provider[T]) -> None:
        """
        Resets a provider to its initial state.
        """
        provider.reset(self._container)
    
    def get_metadata(self, provider: Provider, key=None, default=None):
        """Gets metadata for a provider."""
        return provider.get_metadata(self._container, key, default)
    
    def set_metadata(self, provider: Provider, key, value):
        """Sets metadata for a provider."""
        provider.set_metadata(self._container, key, value)
    
    def get_dependents(self, provider: Provider) -> Set[str]:
        """
        Get all providers that depend on the given provider.
        """
        return self.get_metadata(provider, 'dependents', set())
    
    def get_dependencies(self, provider: Provider) -> List[str]:
        """
        Get all providers that the given provider depends on.
        """
        return self.get_metadata(provider, 'dependencies', [])

    def dispose_effect(self, effect_provider: EffectProvider) -> None:
        """
        Disposes of an effect provider.
        """
        effect_provider.dispose(self._container)
    
    def create_family(self, factory: Callable[[T], Provider[R]], name_prefix=None) -> FamilyProvider[T, R]:
        """
        Creates a provider family.
        """
        return FamilyProvider(factory, name_prefix)
    
    def snapshot(self) -> Dict[str, Any]:
        """
        Creates a snapshot of the current state of all providers.
        """
        return {key: value for key, value in self._container._providers.items()}
    
    def restore(self, snapshot: Dict[str, Any]) -> None:
        """
        Restores the state of providers from a snapshot.
        """
        for key, value in snapshot.items():
            if key in self._container._providers:
                previous_value = self._container._providers[key]
                self._container._providers[key] = value
                self._container._notify_listeners(key, previous_value, value)


def provider_method(method):
    """
    Decorator for methods that should be automatically registered as providers.
    
    Usage:
    
    class MyService:
        def __init__(self, container):
            self.container = container
            self._register_providers()
        
        def _register_providers(self):
            for name in dir(self):
                attr = getattr(self, name)
                if hasattr(attr, '_is_provider_method'):
                    attr()
        
        @provider_method
        def user_provider(self):
            return StateProvider(None, name="user")
    """
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        result = method(self, *args, **kwargs)
        if isinstance(result, Provider):
            self.container.get(result)  # Initialize the provider
        return result
    
    wrapper._is_provider_method = True
    return wrapper