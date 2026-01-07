import weakref
import asyncio
import json
from collections import defaultdict
from typing import Callable, Any, List, Dict, Union, Optional
from js import document, setTimeout, console
from metafor.utils.html import html_sanitize
from pyodide.ffi import create_proxy, JsProxy
from copy import deepcopy
from contextlib import contextmanager

from metafor.utils.html import preserve_whitespace
from metafor.exceptions import global_error_handler

# Global state for reactive system
_current_effect = None
_effects = weakref.WeakKeyDictionary()
_trackable = False
_batch_updates_active = False
_batch_updates_queue = []
_global_error_handler = global_error_handler

def set_global_error_handler(handler: Callable[[Exception], None]):
    """Sets a global error handler for uncaught exceptions."""
    global _global_error_handler
    _global_error_handler = handler

def get_current_effect():
    global _current_effect
    return _current_effect

def get_effects():
    global _effects
    return _effects

@contextmanager
def suspend_tracking():
    global _trackable
    prev_trackable = _trackable
    _trackable = False
    try:
        yield
    finally:
        _trackable = prev_trackable

# Scheduler for batching updates
class Scheduler:
    def __init__(self):
        self.queue = set()
        self.scheduled = False

    def enqueue(self, task):
        self.queue.add(task)
        if not self.scheduled:
            self.scheduled = True
            try:
                loop = asyncio.get_event_loop()
                loop.create_task(self.flush())
            except RuntimeError:
                # Fallback for environments without a running loop (though one should exist)
                 pass

    async def flush(self):
        # Allow other tasks to run (yielding control)
        await asyncio.sleep(0)
        
        while self.queue:
            # Snapshot the current queue to avoid infinite loops if tasks re-enqueue
            tasks = list(self.queue)
            self.queue.clear()
            
            for task in tasks:
                 try:
                     if hasattr(task, 'run'):
                         task.run()
                     elif callable(task):
                         res = task()
                         if asyncio.iscoroutine(res):
                             loop = asyncio.get_event_loop()
                             loop.create_task(res)
                 except Exception as e:
                     if _global_error_handler:
                         _global_error_handler(e)
                     else:
                         console.error(f"Error executing scheduled task: {e}")
            
            # Yield again to allow IO or other tasks if queue refills immediately? 
            # For now, we clear one batch. If more is added, self.scheduled is still True?
            # Actually we should reset scheduled flag *after* we are done or *before*?
            # If we reset before loop, a new task creates a new flush task.
            # Let's reset at the very end.
        
        self.scheduled = False

_scheduler = Scheduler()

def batch_updates(fn):
    global _batch_updates_active, _batch_updates_queue
    prev_state = _batch_updates_active
    _batch_updates_active = True
    try:
        return fn()
    finally:
        _batch_updates_active = prev_state
        if not _batch_updates_active:
            queue_to_process = list(_batch_updates_queue)
            _batch_updates_queue.clear()
            for signal, new_value in queue_to_process:
                signal._set_value_internal(new_value)

class ReactiveDict(dict):
    def __init__(self, data=None, on_change=None):
        super().__init__()
        self.on_change = on_change
        self._initializing = True  # Suppress notifications during init
        
        if data:
            for key, value in data.items():
                if isinstance(value, dict):
                    self[key] = ReactiveDict(value, lambda p=None: self._notify_change(None))
                elif isinstance(value, list):
                    self[key] = ReactiveList(value, lambda p=None: self._notify_change(None))
                else:
                    self[key] = value
        
        self._initializing = False
    
    def __setitem__(self, key, value):
        try:
            if isinstance(value, dict) and not isinstance(value, ReactiveDict):
                value = ReactiveDict(value, lambda p=None: self._notify_change(None))
            elif isinstance(value, list) and not isinstance(value, ReactiveList):
                value = ReactiveList(value, lambda p=None: self._notify_change(None))
                
            super().__setitem__(key, value)
            self._notify_change(key)
        except Exception as e:
            self._handle_error(e, f"Error setting item in ReactiveDict with key: {key}")
    
    def __getitem__(self, key):
        return super().__getitem__(key)
    
    def __delitem__(self, key):
        try:
            super().__delitem__(key)
            self._notify_change(key)
        except Exception as e:
            self._handle_error(e, f"Error deleting item in ReactiveDict with key: {key}")
    
    def _notify_change(self, prop=None):
        if getattr(self, '_initializing', False):
            return
        if self.on_change:
            self.on_change(prop)
            
    def setdefault(self, key, default=None):
        if key in self:
            return self[key]
        self[key] = default
        return self[key]
    
    def update(self, *args, **kwargs):
        try:
            updated = False
            if args:
                if len(args) > 1:
                    raise TypeError("update expected at most 1 argument, got {}".format(len(args)))
                arg = args[0]
                if isinstance(arg, dict):
                    for key in arg:
                        self[key] = arg[key]
                        updated = True
                elif hasattr(arg, "keys"):
                    for key in arg.keys():
                        self[key] = arg[key]
                        updated = True
                else:
                    for key, value in arg:
                        self[key] = value
                        updated = True
            for key, value in kwargs.items():
                self[key] = value
                updated = True
            if updated:
                self._notify_change()
        except Exception as e:
            self._handle_error(e, "Error updating ReactiveDict")
    
    def clear(self):
        try:
            if len(self) > 0:
                super().clear()
                self._notify_change()
        except Exception as e:
            self._handle_error(e, "Error clearing ReactiveDict")
    
    def pop(self, key, *args):
        try:
            result = super().pop(key, *args)
            self._notify_change(key)
            return result
        except Exception as e:
            self._handle_error(e, f"Error popping item from ReactiveDict with key: {key}")
    
    def popitem(self):
        try:
            result = super().popitem()
            self._notify_change()
            return result
        except Exception as e:
            self._handle_error(e, "Error popping item from ReactiveDict")
    
    def _handle_error(self, error, message):
        if _global_error_handler:
            _global_error_handler(error)
        else:
            console.error(f"{message}: {str(error)}")

class ReactiveList(list):
    def __init__(self, data=None, on_change=None):
        super().__init__()
        self.on_change = on_change
        self._initializing = True  # Suppress notifications during init
        
        if data:
            for item in data:
                if isinstance(item, dict):
                    self.append(ReactiveDict(item, lambda p=None: self._notify_change(None)))
                elif isinstance(item, list):
                    self.append(ReactiveList(item, lambda p=None: self._notify_change(None)))
                else:
                    self.append(item)
        
        self._initializing = False
    
    def _notify_change(self, prop=None):
        if getattr(self, '_initializing', False):
            return
        if self.on_change:
            self.on_change(prop)
    
    def __setitem__(self, index, value):
        try:
            if isinstance(value, dict) and not isinstance(value, ReactiveDict):
                value = ReactiveDict(value, lambda p=None: self._notify_change(None))
            elif isinstance(value, list) and not isinstance(value, ReactiveList):
                value = ReactiveList(value, lambda p=None: self._notify_change(None))
                
            super().__setitem__(index, value)
            self._notify_change()
        except Exception as e:
            self._handle_error(e, f"Error setting item in ReactiveList at index: {index}")
    
    def __getitem__(self, index):
        return super().__getitem__(index)
    
    def __delitem__(self, index):
        try:
            super().__delitem__(index)
            self._notify_change()
        except Exception as e:
            self._handle_error(e, f"Error deleting item in ReactiveList at index: {index}")
    
    def append(self, item):
        try:
            if isinstance(item, dict) and not isinstance(item, ReactiveDict):
                item = ReactiveDict(item, lambda p=None: self._notify_change(None))
            elif isinstance(item, list) and not isinstance(item, ReactiveList):
                item = ReactiveList(item, lambda p=None: self._notify_change(None))
                
            super().append(item)
            self._notify_change()
        except Exception as e:
            self._handle_error(e, "Error appending item to ReactiveList")
    
    def extend(self, iterable):
        try:
            items = list(iterable)
            for i, item in enumerate(items):
                if isinstance(item, dict) and not isinstance(item, ReactiveDict):
                    items[i] = ReactiveDict(item, lambda p=None: self._notify_change(None))
                elif isinstance(item, list) and not isinstance(item, ReactiveList):
                    items[i] = ReactiveList(item, lambda p=None: self._notify_change(None))
            
            super().extend(items)
            self._notify_change()
        except Exception as e:
            self._handle_error(e, "Error extending ReactiveList")
    
    def insert(self, index, item):
        try:
            if isinstance(item, dict) and not isinstance(item, ReactiveDict):
                item = ReactiveDict(item, lambda p=None: self._notify_change(None))
            elif isinstance(item, list) and not isinstance(item, ReactiveList):
                item = ReactiveList(item, lambda p=None: self._notify_change(None))
                
            super().insert(index, item)
            self._notify_change()
        except Exception as e:
            self._handle_error(e, f"Error inserting item into ReactiveList at index: {index}")
    
    def remove(self, item):
        try:
            super().remove(item)
            self._notify_change()
        except Exception as e:
            self._handle_error(e, "Error removing item from ReactiveList")
    
    def pop(self, index=-1):
        try:
            result = super().pop(index)
            self._notify_change()
            return result
        except Exception as e:
            self._handle_error(e, f"Error popping item from ReactiveList at index: {index}")
    
    def clear(self):
        try:
            if len(self) > 0:
                super().clear()
                self._notify_change()
        except Exception as e:
            self._handle_error(e, "Error clearing ReactiveList")
    
    def sort(self, *args, **kwargs):
        try:
            super().sort(*args, **kwargs)
            self._notify_change()
        except Exception as e:
            self._handle_error(e, "Error sorting ReactiveList")
    
    def reverse(self):
        try:
            super().reverse()
            self._notify_change()
        except Exception as e:
            self._handle_error(e, "Error reversing ReactiveList")
    
    def _handle_error(self, error, message):
        if _global_error_handler:
            _global_error_handler(error)
        else:
            console.error(f"{message}: {str(error)}")

class Signal:
    __slots__ = ('_deep', '_subscribers', '_before_callbacks', '_after_callbacks', 
                 '_prop_subscribers', '_disposed', '_value', '__weakref__')

    def __init__(self, initial_value: Any, deep: bool = False):
        self._deep = deep
        self._subscribers = set()
        self._before_callbacks = []
        self._after_callbacks = []
        self._prop_subscribers = defaultdict(set)
        self._disposed = False
        self._value = self._make_reactive(initial_value) if deep else initial_value
    
    def _make_reactive(self, value):
        if not self._deep:
            return value
        if isinstance(value, dict) and not isinstance(value, ReactiveDict):
            return ReactiveDict(value, self._notify_change)
        elif isinstance(value, list) and not isinstance(value, ReactiveList):
            return ReactiveList(value, self._notify_change)
        return value
    
    def _notify_change(self, prop=None):
        old_value = self._value
        if self._before_callbacks:
            try:
                for callback in self._before_callbacks:
                    callback(old_value, old_value)
            except Exception as e:
                self._handle_error(e, "Error in _before_callbacks")
        
        if self._subscribers:
            subscribers_snapshot = list(self._subscribers)
            for subscriber in subscribers_snapshot:
                if subscriber is not None:
                    try:
                        # If it's an Effect, schedule it.
                        # If it's a Memo (or something else needing sync), run clearly.
                        # Duck typing: check for 'run' method that doesn't take args (Effect.run)
                        # Subscriber.notify takes args. 
                        # Ideally, subscriber.notify is what we call.
                        # But Effect.notify checks dirty and calls run.
                        # Let's see Effect structure. Effect.notify calls self.run().
                        # If we use the Scheduler, we likely wait to call subscriber.notify 
                        # OR we manually mark dirty and schedule Effect.run().
                        
                        # Simplified scheduling:
                        if isinstance(subscriber, Effect):
                            # Mark dirty immediately to prevent redundant scheduling/computations?
                            # Effect.notify does dirty check.
                            # We can just schedule the notification call itself?
                            # But Scheduler expects a task with .run(). 
                            # Let's wrap the notify call or assume subscriber puts itself in scheduler.
                            # Better: We modify Signal to simply enqueue the subscriber if it is an Effect.
                            subscriber.dirty = True # Mark dirty synchronously
                            _scheduler.enqueue(subscriber)
                        else:
                            subscriber.notify(self, old_value, old_value, prop)
                    except Exception as e:
                        self._handle_error(e, f"Error notifying subscriber: {subscriber}")
        
        if prop is not None and self._prop_subscribers.get(prop):
            subscribers_snapshot = list(self._prop_subscribers[prop])
            for subscriber in subscribers_snapshot:
                if subscriber is not None:
                    try:
                        if isinstance(subscriber, Effect):
                            subscriber.dirty = True
                            _scheduler.enqueue(subscriber)
                        else:
                            subscriber.notify(self, old_value, old_value, prop)
                    except Exception as e:
                        self._handle_error(e, f"Error notifying property subscriber: {subscriber}")

        if self._after_callbacks:
            try:
                for callback in self._after_callbacks:
                    callback()
            except Exception as e:
                self._handle_error(e, "Error in _after_callbacks")

    def __call__(self, prop=None) -> Any:
        global _current_effect, _trackable
        # Optimized: Inline get() logic to remove function call overhead
        if not _trackable:
            return getattr(self._value, prop) if prop else self._value
        if _current_effect:
            if prop is not None:
                self._prop_subscribers[prop].add(_current_effect)
            else:
                self._subscribers.add(_current_effect)
            # direct access to Effect internals to avoid getattr if possible, 
            # but _current_effect is an instance.
            if hasattr(_current_effect, 'dependencies') and self not in _current_effect.dependencies:
                _effects[_current_effect]["dependencies"].add(self)
        return getattr(self._value, prop) if prop else self._value

    # Alias get to __call__ to avoid code duplication and maintain performance
    get = __call__

    def peek(self):
        return self._value
    
    def set(self, new_value: Any) -> None:
        if self._deep and isinstance(new_value, (dict, list)):
            reactive_value = self._make_reactive(new_value)
            queue_update(self, reactive_value)
        else:
            queue_update(self, new_value)
    
    def _set_value_internal(self, new_value):        
        if self._deep and (isinstance(self._value, (ReactiveDict, ReactiveList)) or isinstance(new_value, (dict, list))):
            try:
                old_json = json.dumps(self._value)
                new_json = json.dumps(new_value)
                if old_json == new_json:
                    return
            except (TypeError, ValueError):
                if self._value == new_value:
                    return
        elif self._value == new_value:
            return

        old_value = self._value
        self._value = self._make_reactive(new_value) if self._deep and isinstance(new_value, (dict, list)) else new_value
        
        try:
            for callback in self._before_callbacks:
                callback(old_value, new_value)
        except Exception as e:
            self._handle_error(e, "Error in _before_callbacks")

        subscribers_snapshot = list(self._subscribers)
        for subscriber in subscribers_snapshot:
            if subscriber is not None:
                try:
                    if isinstance(subscriber, Effect):
                        subscriber.dirty = True
                        _scheduler.enqueue(subscriber)
                    else:
                        subscriber.notify(self, old_value, new_value)
                except Exception as e:
                    self._handle_error(e, f"Error notifying subscriber: {subscriber}")

        for prop, subscribers in list(self._prop_subscribers.items()):
            has_changed = False
            old_has_prop = hasattr(old_value, prop)
            new_has_prop = hasattr(new_value, prop)
            
            if old_has_prop and new_has_prop:
                if getattr(old_value, prop) != getattr(new_value, prop):
                    has_changed = True
            elif old_has_prop or new_has_prop:
                has_changed = True
            if has_changed:
                subscribers_snapshot = list(subscribers)
                for subscriber in subscribers_snapshot:
                    if subscriber is not None:
                        try:
                            if isinstance(subscriber, Effect):
                                subscriber.dirty = True
                                _scheduler.enqueue(subscriber)
                            else:
                                subscriber.notify(self, old_value, new_value, prop)
                        except Exception as e:
                            self._handle_error(e, f"Error notifying property subscriber: {subscriber}")

        try:
            for callback in self._after_callbacks:
                callback()
        except Exception as e:
            self._handle_error(e, "Error in _after_callbacks")
    
    def _handle_error(self, error, message):
        if _global_error_handler:
            _global_error_handler(error)
        else:
            console.error(f"{message}: {str(error)}")

def create_signal(initial_value: Any, deep: bool = False):
    signal = Signal(initial_value, deep=deep)
    return signal, signal.set

def unwrap(value: Any) -> Any:
    """
    Unwraps a Signal to get its value, or returns the value if it's not a Signal.
    """
    if isinstance(value, Signal):
        return value()
    return value

def queue_update(signal, new_value):
    global _batch_updates_active, _batch_updates_queue
    if _batch_updates_active:
        _batch_updates_queue.append((signal, new_value))
    else:
        signal._set_value_internal(new_value)

class Effect:
    __slots__ = ('fn', 'dependencies', 'children', 'disposals', 'mounts', 
                 'is_running', 'disposed', 'dirty', '_last_dependency_values', 
                 '_subscribed_props', '_error_count', '_max_errors', '__weakref__')

    def __init__(self, fn: Callable[[], Any]):
        self.fn = fn
        self.dependencies: set = set()
        self.children: set = set()
        self.disposals: List[Callable[[], None]] = []
        self.mounts: List[Callable[[], None]] = []
        self.is_running = False
        self.disposed = False
        self.dirty = False
        self._last_dependency_values = {}
        self._subscribed_props: Dict[Signal, Set[str]] = defaultdict(set)
        self._error_count = 0
        self._max_errors = 5  # Maximum number of errors before stopping

    
    def notify(self, signal, old_value, new_value, prop=None):
        if self.dirty:
            return
        if prop is not None:
            if signal in self._subscribed_props and prop in self._subscribed_props[signal]:
                old_has_prop = hasattr(old_value, prop)
                new_has_prop = hasattr(new_value, prop)

                if old_has_prop and new_has_prop:
                    if getattr(old_value, prop) != getattr(new_value, prop):
                        self.dirty = True
                elif old_has_prop or new_has_prop:
                    self.dirty = True
        else:
            self.dirty = True
        if self.dirty:
            self.run()
    
    def run(self):
        if self.disposed or self.is_running:
            return
        if self._error_count >= self._max_errors:
            raise Exception(f"Effect has exceeded maximum error count ({self._max_errors}). Stopping execution.")
        
        self.is_running = True
        self.dirty = False
        global _current_effect, _trackable
        prev_effect = _current_effect
        prev_trackable = _trackable
        _current_effect = self

        self._cleanup()

        try:
            _trackable = True
            self.fn() # Execute effect callback
            self._error_count = 0  # Reset error count on successful run
        except Exception as e:
            self._error_count += 1
            self._handle_error(e, "Error running effect")
        finally:
            _trackable = False
            _current_effect = prev_effect
            self.is_running = False
        
    
    def run_mounts(self):
        for mount in self.mounts:
            _scheduler.enqueue(mount)
        self.mounts.clear()

    def remove_dependency(self, signal):
        if signal in self.dependencies:
            self.dependencies.remove(signal)
            if signal in self._last_dependency_values:
                del self._last_dependency_values[signal]
            if signal in self._subscribed_props:
                del self._subscribed_props[signal]
    
    def _cleanup(self):
        for signal in list(self.dependencies):
            if hasattr(signal, "_subscribers"):
                signal._subscribers.discard(self)

            for prop in list(signal._prop_subscribers.keys()):
                if self in signal._prop_subscribers[prop]:
                    signal._prop_subscribers[prop].discard(self)
                    
        self.dependencies.clear()
        self._last_dependency_values.clear()
        self._subscribed_props.clear()

        for dispose in self.disposals:
            try:
                dispose()
            except Exception as e:
                self._handle_error(e, "Cleanup error")
        self.disposals.clear()
    
    def dispose(self):
        if self.disposed:
            return
        self.disposed = True
        for child in list(self.children):
            child.dispose()
        self._cleanup()
        if _current_effect and self in _effects.get(_current_effect, {}).get("children", set()):
            _effects[_current_effect]["children"].discard(self)
    
    def _handle_error(self, error, message):
        if _global_error_handler:
            _global_error_handler(error)
        else:
            console.error(f"{message}: {str(error)}")

def create_effect(fn: Callable[[], Any]) -> Effect:
    effect = Effect(fn)
    parent_effect = _current_effect

    if parent_effect:
        _effects[parent_effect]["children"].add(effect)
    
    _effects[effect] = {
        "dependencies": effect.dependencies,
        "children": effect.children,
        "disposals": effect.disposals,
        "mounts": effect.mounts
    }
    effect.run()
    return effect

def untrack(fn: Callable[[], Any]) -> Any:
    global _current_effect, _trackable
    if not callable(fn):
        raise TypeError(f"untrack: expected callable, got {type(fn).__name__}")
    prev_effect = _current_effect
    prev_tracking = _trackable
    _trackable = False
    try:
        return fn()
    finally:
        _trackable = prev_tracking
        _current_effect = prev_effect

def track(fn: Callable[[], Any]) -> Any:
    global _trackable
    if not callable(fn):
        raise TypeError(f"track: expected callable, got {type(fn).__name__}")
    prev_trackable = _trackable
    _trackable = True
    try:
        return fn()
    finally:
        _trackable = prev_trackable

class Memo:
    """
    Memo implementation using composition.
    It contains an internal Signal to store the computed value.
    """
    def __init__(self, compute_fn: Callable[[], Any]):
        if not callable(compute_fn):
            raise TypeError("compute_fn must be a callable function")

        self._compute_fn = compute_fn
        self._signal, self._set_signal = create_signal(None)
        self._effect = weakref.ref(create_effect(self._update))
        on_dispose(self.dispose)


    def _update(self):
        """
        Recomputes the value using the compute_fn and updates the internal signal
        if the value has changed.
        """
        try:
            # Execute the computation function. Dependency tracking happens here.
            new_value = self._compute_fn()
            # Get Signal value without creating a dependency loop if the memo reads itself.
            with suspend_tracking():
                current_value = self._signal()

            if current_value != new_value:
                # Update the internal signal, which will notify its subscribers.
                self._set_signal(new_value)
        except Exception as e:
            print(f"Error updating Memo: {e}")

    def __call__(self) -> Any:
        """
        Reads the memoized signal value and automatically tracks this memo as a dependency
        in the current effect context.
        """
        # Simply call the internal signal to get its value and register dependency
        return self._signal()
    
    def peek(self) -> Any:
        """Reads the current memoized value without creating a dependency."""
        return self._signal.peek()

    def dispose(self):
        """
        Cleans up the internal effect associated with this memo, prevent memory leaks.
        """
        effect = self._effect()
        if effect:
            effect.dispose()
        self._effect = None # Ensure the reference is cleared

class LinkedSignal(Signal):
    """
    A signal that derives its value from one or more source signals and a compute function.
    Works like Angular's LinkedSignal: manual updates persist until source signals change.
    """
    def __init__(self, *sources: Signal, compute_fn: Callable):
        super().__init__(None)  # Initial value is None, will be computed
        if not sources:
            raise ValueError("At least one source signal is required")
        # Validate that each source is a Signal, Memo, or LinkedSignal instance
        # Note: LinkedSignal is a subclass of Signal, so isinstance check covers it
        for i, source in enumerate(sources):
            if not isinstance(source, (Signal, Memo)):
                raise TypeError(f"Source at index {i} must be a Signal, Memo, or LinkedSignal instance, got {type(source).__name__}")
        self._sources = sources
        self._compute_fn = compute_fn
        self._manual_update = False  # Track if value was manually set
        self._effect = create_effect(self._update)
        # Initialize with computed value
        self._update()

    def _update(self):
        """
        Recompute the derived value when dependencies change.
        This overrides any manual update - when source signals change,
        we always recompute and reset the manual flag.
        """
        # Source signal changed, so reset manual flag and recompute
        was_manual = self._manual_update
        self._manual_update = False
        source_values = tuple(source() for source in self._sources)
        new_value = self._compute_fn(*source_values)
        if self._value != new_value or was_manual:
            self._set_value_internal(new_value)

    def set(self, new_value: Any):
        """
        Set the value of the linked signal manually.
        The value will persist until source signals change.
        """
        self._manual_update = True
        if self._value != new_value:
            self._set_value_internal(new_value)



class RefHolder:
    """
    A unified ref holder that supports both HTML element refs and component refs.
    Provides a common interface for both use cases.
    
    Usage for HTML element refs:
        form_ref = ref_bind()
        <form ref:=form_ref />
        form_element = form_ref.current  # Access the DOM element
    
    Usage for component refs:
        form_ref = ref_bind()
        <ChildComponent ref:=form_ref />
        form_ref.handle_submit()  # Access exposed methods/variables
        form_ref.expose("method_name", method)  # In child component
    """
    def __init__(self):
        self._data = {}
        self._current = None  # For HTML element refs
    
    def __getitem__(self, key):
        # Special handling for 'current' to support HTML element refs
        if key == "current":
            return self._current
        return self._data[key]
    
    def __setitem__(self, key, value):
        # Special handling for 'current' to support HTML element refs
        if key == "current":
            self._current = value
        else:
            self._data[key] = value
    
    def __contains__(self, key):
        if key == "current":
            return self._current is not None
        return key in self._data
    
    def __getattr__(self, name):
        if name.startswith('_'):
            # Allow access to private attributes
            return object.__getattribute__(self, name)
        # Special handling for 'current' to support HTML element refs
        if name == "current":
            return self._current
        if name in self._data:
            return self._data[name]
        raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")
    
    def __setattr__(self, name, value):
        if name.startswith('_'):
            super().__setattr__(name, value)
        elif name == "current":
            # Direct assignment to current (for HTML element refs)
            super().__setattr__("_current", value)
        else:
            if not hasattr(self, '_data'):
                super().__setattr__('_data', {})
            self._data[name] = value
    
    def keys(self):
        """Return the keys in the ref data (excluding 'current')."""
        keys = list(self._data.keys())
        if self._current is not None:
            keys.append("current")
        return keys
    
    def get(self, key, default=None):
        """Get a value from the ref data with optional default."""
        if key == "current":
            return self._current if self._current is not None else default
        return self._data.get(key, default)
    
    def expose(self, name_or_value: Union[str, Callable, Any], value: Optional[Any] = None) -> None:
        """
        Expose a method or variable to the parent component.
        This is used when RefHolder is used as a component ref.
        
        Can be called in two ways:
        1. expose(function) - Uses the function's name as the key
        2. expose(name, value) - Explicitly sets the name and value
        
        Args:
            name_or_value: If callable and value is None, uses function name as key.
                          Otherwise, this is the name (str) to expose.
            value: The function or value to expose. If None and name_or_value is callable,
                   uses name_or_value's name as the key.
        """
        if value is None and callable(name_or_value):
            # Called as expose(function) - use function name as key
            func_name = getattr(name_or_value, '__name__', 'anonymous')
            self._data[func_name] = name_or_value
        elif isinstance(name_or_value, str) and value is not None:
            # Called as expose(name, value) - explicit name and value
            self._data[name_or_value] = value
        else:
            # Fallback: treat name_or_value as the value and try to get a name
            if callable(name_or_value):
                func_name = getattr(name_or_value, '__name__', 'anonymous')
                self._data[func_name] = name_or_value
            else:
                # Non-callable without explicit name - raise error
                raise ValueError("expose() requires either a callable or (name, value) pair")
    
    
    @property
    def current(self):
        """
        Get the current HTML element (for HTML element refs).
        Returns None if no element has been set.
        """
        return self._current


def create_ref() -> RefHolder:
    """
    Create a new RefHolder instance for component refs.
    
    Usage:
        form_ref = create_ref()
        <ChildComponent ref:=form_ref />
        form_ref.handle_submit()  # Access exposed methods/variables
    
    Returns:
        A new RefHolder instance
    """
    return RefHolder()



def on_dispose(fn: Callable[[], None]) -> None:
    if _current_effect:
        _effects[_current_effect]["disposals"].append(fn)

def on_mount(callback: Callable[[], None]):
    if _current_effect:
        if "mounts" not in _effects[_current_effect]:
            _effects[_current_effect]["mounts"] = []

        def scheduled_callback():
            setTimeout(create_proxy(callback), 0)

        _effects[_current_effect]["mounts"].append(scheduled_callback)

def before_update(signals: Signal, callback: Callable[[], None]):
    if not isinstance(signals, list):
        signals = [signals]

    for signal in signals:
        signal._before_callbacks.append(callback)

def after_update(signals: Signal, callback: Callable[[], None]):
    if not isinstance(signals, list):
        signals = [signals]

    for signal in signals:
        signal._after_callbacks.append(callback)

