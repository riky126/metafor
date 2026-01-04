# /Users/ricardo/metafor/metafor/form/form.py
from typing import Dict, Any, Callable, Optional, List, Union, Set, TypeVar, cast
import asyncio
import time
from copy import deepcopy

from metafor.hooks import create_derived
from metafor.core import create_signal, Signal, batch_updates, track
from metafor.decorators import reusable

from metafor.form.schema import Schema

# Time in milliseconds to wait before running debounced validation
# Time in milliseconds to wait before running debounced validation
DEFAULT_DEBOUNCE_MS = 200

_UNSET = object()

class FieldUsage:
    """
    Represents metadata about a form field.
    """
    valid: bool
    errors: List[str]
    touched: bool
    dirty: bool
    value: Any
    set_value: Callable[[Any], None]
    _get_meta: Callable

    def __init__(self, value: Any, set_value: Callable[[Any], None], get_meta: Callable):

        self.value = value
        self.set_value = set_value
        self._get_meta = get_meta
        self._set_meta(self._get_meta())

    @property
    def meta(self) -> Dict[str, Any]:
        metadata = self._get_meta()
        self._set_meta(metadata)
        return self
    
    @property
    def error(self) -> str:
        if len(self.errors):
            return self.errors[0]
        return None
    
    @property
    def is_empty(self) -> str:
        if self.value() is None or not self.value():
            return True
        return False
    
    def _set_meta(self, metadata: Dict[str, Any]) -> None:
        self.valid = metadata.get("is_valid", True)
        self.errors = metadata.get("errors", None)
        self.touched = metadata.get("is_touched", False)
        self.dirty = metadata.get("is_dirty", False)

class FieldAccessProxy:
    """
    Proxy for cleaner field access syntax.
    Enables usage like: form.F.user.email or form.F.items[0].name
    """
    def __init__(self, form: 'Form', path: str = ""):
        self._form = form
        self._path = path

    def __getattr__(self, name: str) -> 'FieldAccessProxy':
        new_path = f"{self._path}.{name}" if self._path else name
        return FieldAccessProxy(self._form, new_path)

    def __getitem__(self, key: Union[int, str]) -> 'FieldAccessProxy':
        if isinstance(key, int):
            # Array index: items[0]
            new_path = f"{self._path}[{key}]"
        else:
            # Dict key: items['name'] (rarely used but supported)
            new_path = f"{self._path}.{key}" if self._path else key
        return FieldAccessProxy(self._form, new_path)

    def _get_field(self) -> FieldUsage:
        field = self._form.field(self._path)
        if field is None:
            # Should we return a dummy or error?
            # Existing behavior of field() prints warning and returns None.
            # But let's assume valid access for now or let it fail if user tries to specific ops
            raise AttributeError(f"Field '{self._path}' not found")
        return field

    @property
    def value(self) -> Any:
        return self._get_field().value()
        
    def set_value(self, val: Any) -> None:
        self._get_field().set_value(val)
        
    @property
    def meta(self) -> Dict[str, Any]:
        return self._get_field().meta
        
    @property
    def valid(self) -> bool:
        return self.meta.valid
        
    @property
    def errors(self) -> List[str]:
        return self.meta.errors
        
    @property
    def error(self) -> Optional[str]:
        return self.meta.error
        
    @property
    def touched(self) -> bool:
        return self.meta.touched
        
    @property
    def dirty(self) -> bool:
        return self.meta.dirty
    
    # Allow calling the proxy to get the raw FieldUsage object if needed, 
    # though properties cover most cases.  
    def __call__(self) -> FieldUsage:
        return self._get_field()
        
class Form:
    """
    Manages form state, validation, and submission.
    """
    def __init__(self, initial_values: Dict[str, Any], fields_schema: Schema):
        self.form_data, self.set_form_data = create_signal(initial_values, deep=True)
        self.errors, self.set_errors = create_signal({})
        self.touched, self.set_touched = create_signal({})
        self.dirty, self.set_dirty = create_signal({})  # Track if fields have been modified
        self.is_submitting, self.set_is_submitting = create_signal(False)
        self.schema = fields_schema
        self.initial_values = deepcopy(initial_values)  # Store initial values for reset
        self.debounce_timers = {}  # Store timers for debounced validation
        self.validation_strategy = "onchange"  # Default validation strategy
        
        # Meta state for the entire form
        self.meta, self.set_meta = create_signal({
            "is_valid": True,
            "is_dirty": False,
            "is_touched": False,
            "validated_at": None
        })

    @property
    def F(self) -> FieldAccessProxy:
        """
        Returns a FieldAccessProxy for cleaner field access syntax.
        Usage: form.F.user.email
        """
        return FieldAccessProxy(self)
        
    def field(self, field_name: str) -> Any:
        current_val = self.get_nested_value(field_name) if "." in field_name or "[" in field_name else self.form_data().get(field_name)
        
        # Relaxed check: if it's a nested path, we assume it's valid if get_nested_value returns something 
        # OR if we want to allow binding to null fields that will be created on write.
        # For top-level, we still check key existence or schema existence?
        # Let's check if the path exists in the form data OR in the schema.
        # Since checking schema deep is hard, let's rely on data presence or just allow it.
        
        # Check if value exists or if it's computable
        if True: # defaulting to always returning a field handle if requested, simplifies binding
            def value() -> Any:
                return self.get_nested_value(field_name)
            
            def set_value(new_value: Any) -> None:
                if "." in field_name or "[" in field_name:
                    self.set_nested_value(field_name, new_value)
                else:
                    self.set_form_data({**self.form_data(), field_name: new_value})
                    self.set_dirty({**self.dirty(), field_name: True})
                    self.set_touched({**self.touched(), field_name: True})
                    self.validate_field(field_name, new_value)

            def get_meta() -> Dict[str, Any]:
                errors = self.get_field_errors(field_name)
                return {
                    "errors": errors,
                    **self.get_field_meta(field_name)
                } 
            
            field = FieldUsage(
                value=value,
                set_value=set_value,
                get_meta=get_meta,
            )
                
            return field
        
        print(f"Warning: Field '{field_name}' not found in form data.")
        
        return None
        
    def validate_form(self, async_mode: bool = False) -> Union[bool, asyncio.Future]:
        """
        Validates all form fields.
        
        Args:
            async_mode: If True, perform asynchronous validation and return a Future
                      If False, perform synchronous validation and return boolean
                      
        Returns:
            If async_mode is False: True if form is valid, False otherwise
            If async_mode is True: asyncio.Future that resolves to True if form is valid
        """
        current_data = self.form_data()
        
        if async_mode:
            # Return a future that will resolve when async validation completes
            async def run_async_validation():
                all_errors = await self.schema.validate_async(current_data)
                self.set_errors(all_errors)
                is_valid = not all_errors
                
                # Update meta
                self.set_meta({
                    **self.meta(),
                    "is_valid": is_valid,
                    "validated_at": time.time() * 1000  # Current time in ms
                })
                
                return is_valid
                
            return asyncio.ensure_future(run_async_validation())
        else:
            # Synchronous validation
            all_errors = self.schema.validate(current_data)
            self.set_errors(all_errors)
            is_valid = not all_errors
            
            # Update meta
            self.set_meta({
                **self.meta(),
                "is_valid": is_valid,
                "validated_at": time.time() * 1000  # Current time in ms
            })
            
            return is_valid

    def validate_field(self, field_name: str, value: Any, async_mode: bool = False) -> Union[bool, asyncio.Future]:
        """
        Validates a single form field.
        
        Args:
            field_name: The name of the field to validate
            value: The value to validate
            async_mode: If True, perform asynchronous validation
            
        Returns:
            If async_mode is False: True if field is valid, False otherwise
            If async_mode is True: asyncio.Future that resolves to True if field is valid
        """
        # Handle nested fields
        if "." in field_name:
            parts = field_name.split('.')
            current_schema = self.schema
            
            # Traverse to find the field schema
            for i, part in enumerate(parts[:-1]):
                # Check for array indexing
                if '[' in part and part.endswith(']'):
                    array_name, _ = part.split('[', 1)
                    if array_name in current_schema.field_arrays:
                         current_schema = current_schema.field_arrays[array_name].item_schema
                    else:
                        # Path invalid in schema
                        return True
                elif part in current_schema.nested_schemas:
                    current_schema = current_schema.nested_schemas[part]
                else:
                    # Path invalid in schema
                    return True
            
            last_part = parts[-1]
            # Handle array indexing on the last part (unlikely for a field definition, but possible for value access)
            if '[' in last_part and last_part.endswith(']'):
                 # Validating a specific item in an array primitive?
                 # Not supported by the Schema structure which defines fields by name.
                 # If we are here, we are validating a leaf value. 
                 # If the schema defines an array of primitives, we might need logic here.
                 # For now, let's assume last_part is a field name in the current_schema.
                 pass

            field_schema = current_schema.fields.get(last_part)
            if not field_schema:
                if async_mode:
                    future = asyncio.Future()
                    future.set_result(True)
                    return future
                return True

            # Use the already implemented validation logic below, but we need to ensure
            # we are updating errors with the full path `field_name`.
            # The logic below uses `field_schema` and `field_name` to update errors.
            # We just found the correct `field_schema`.
            # The `field_name` argument is already the full path "user.address.street".
            # The `value` argument is the value of that leaf field.
            
            # Additional check: Conditional validation on the Nested Schema?
            # The current implementation checks `field_schema.conditional_validation`.
            # Does `field_schema.conditional_validation` expect the ROOT form data or the NESTED data?
            # Conventionally in this library so far, everything operates on `self.form_data()` which is root.
            # So passing root data is correct.
            
            # Fall through to normal validation logic using the resolved field_schema
        else:
            field_schema = self.schema.fields.get(field_name)

        if not field_schema:
            if async_mode:
                future = asyncio.Future()
                future.set_result(True)
                return future
            return True

        # Apply trimming if needed before validation
        processed_value = value
        if field_schema.trim_flag and isinstance(value, str):
            processed_value = value.strip()

        if async_mode and field_schema.async_validation_functions:
            # Run asynchronous validation
            async def run_async_validation():
                # First run synchronous validators
                current_data = self.form_data()
                field_errors = []
                
                # Skip if conditional validation is defined and evaluates to False
                if field_schema.conditional_validation and not field_schema.conditional_validation(current_data):
                    self.remove_field_errors(field_name)
                    return True
                
                for validation_func in field_schema.validation_functions:
                    print(f"DEBUG: Running validator on '{processed_value}'")
                    error_message = validation_func(processed_value)
                    if error_message:
                        print(f"DEBUG: Error found: {error_message}")
                    if error_message:
                        field_errors.append(error_message)
                
                # Then run async validators if no errors yet
                if not field_errors:
                    for async_validator in field_schema.async_validation_functions:
                        try:
                            result = async_validator(processed_value)
                            if asyncio.iscoroutine(result):
                                error_message = await result
                            else:
                                error_message = result
                                
                            if error_message:
                                field_errors.append(error_message)
                        except Exception as e:
                            field_errors.append(f"Validation error: {str(e)}")
                
                # Update errors state
                current_errors = self.errors()
                if field_errors:
                    new_errors = {**current_errors, field_name: field_errors}
                else:
                    new_errors = {k: v for k, v in current_errors.items() if k != field_name}
                
                self.set_errors(new_errors)
                
                # Update meta state
                self._update_meta_state()
                
                return not field_errors
            
            return asyncio.ensure_future(run_async_validation())
        else:
            # Run only synchronous validators
            current_data = self.form_data()
            field_errors = []
            
            # Skip if conditional validation is defined and evaluates to False  
            if field_schema.conditional_validation and not field_schema.conditional_validation(current_data):
                self.remove_field_errors(field_name)
                return True
            
            for validation_func in field_schema.validation_functions:
                error_message = validation_func(processed_value)
                if error_message:
                    field_errors.append(error_message)

            current_errors = self.errors()
            
            if field_errors:
                new_errors = {**current_errors, field_name: field_errors}
            else:
                new_errors = {k: v for k, v in current_errors.items() if k != field_name}

            if new_errors != current_errors:
                self.set_errors(new_errors)
                
            # Update meta state
            self._update_meta_state()
            
            return not field_errors
    
    def remove_field_errors(self, field_name: str) -> None:
        """Removes all errors for a specific field."""
        current_errors = self.errors()
        if field_name in current_errors:
            new_errors = {k: v for k, v in current_errors.items() if k != field_name}
            self.set_errors(new_errors)
            self._update_meta_state()

    def _update_meta_state(self) -> None:
        """Updates the meta state of the form based on current errors, touched, and dirty states."""
        current_errors = self.errors()
        current_touched = self.touched()
        current_dirty = self.dirty()
        
        self.set_meta({
            **self.meta(),
            "is_valid": not current_errors,
            "is_touched": bool(current_touched),
            "is_dirty": bool(current_dirty)
        })

    def handle_change(self, field_name: str, debounce_ms: int = None) -> Callable[[Any], None]:
        """
        Creates an input change handler for a specific field, with optional debouncing.
        
        Args:
            field_name: The field to handle changes for
            debounce_ms: If provided, validation will be debounced by this many milliseconds
                        If None, the default validation strategy for the field will be used
        """
        field_schema = self.schema.fields.get(field_name)
        validation_strategy = field_schema.validation_strategy if field_schema else self.validation_strategy
        should_debounce = debounce_ms is not None or validation_strategy == "onchange"
        
        def handler(event):
            new_value = event.target.value
            if event.target.type == "checkbox":
                new_value = event.target.checked

            # Apply trimming based on schema
            field_schema = self.schema.fields.get(field_name)
            processed_value = new_value
            if field_schema and field_schema.trim_flag and isinstance(new_value, str):
                processed_value = new_value.strip()

            def perform_updates():
                current_form_data = self.form_data()
                current_dirty = self.dirty()
                
                # Check if value is different from initial to mark as dirty
                is_dirty = processed_value != self.initial_values.get(field_name)
                
                # Store the potentially trimmed value
                self.set_form_data({**current_form_data, field_name: processed_value})
                self.set_dirty({**current_dirty, field_name: is_dirty})
                
                # Only set touched or validate if using "onchange" strategy
                if validation_strategy == "onchange":
                    self.set_touched({**self.touched(), field_name: True})
                    
                    # If debouncing is enabled, delay validation
                    if should_debounce and debounce_ms is not None:
                        # Cancel existing timer for this field if any
                        if field_name in self.debounce_timers:
                            self.debounce_timers[field_name].cancel()
                            
                        # Schedule new validation with delay
                        async def delayed_validation():
                            try:
                                await asyncio.sleep(debounce_ms / 1000)  # Convert ms to seconds
                                # Validate with the latest value when timer expires
                                latest_value = self.form_data().get(field_name)
                                self.validate_field(field_name, latest_value, async_mode=True)
                            finally:
                                if field_name in self.debounce_timers:
                                    del self.debounce_timers[field_name]
                                    
                        self.debounce_timers[field_name] = asyncio.ensure_future(delayed_validation())
                    else:
                        # Validate immediately
                        self.validate_field(field_name, processed_value)
                
                # Update meta state
                self._update_meta_state()

            batch_updates(perform_updates)

        return handler
        
    def handle_blur(self, field_name: str) -> Callable[[Any], None]:
        """Creates an input blur handler for a specific field."""
        field_schema = self.schema.fields.get(field_name)
        validation_strategy = field_schema.validation_strategy if field_schema else self.validation_strategy
        
        def handler(event):
            def perform_updates():
                # Mark field as touched
                self.set_touched({**self.touched(), field_name: True})
                
                # Validate on blur if that's the strategy
                if validation_strategy == "onblur":
                    current_value = self.form_data().get(field_name)
                    self.validate_field(field_name, current_value, async_mode=True)
                
                # Update meta state
                self._update_meta_state()
                
            batch_updates(perform_updates)
            
        return handler

    def bind_input(self, field_name: str, validation_options: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Binds an input element to a form field.
        
        Args:
            field_name: The name of the field to bind
            validation_options: Optional configuration for validation:
                - debounce_ms: Milliseconds to debounce validation (default: None)
                
        Returns:
            A dictionary of props to be spread onto an input element
        """
        options = validation_options or {}
        debounce_ms = options.get("debounce_ms", None)
        
        if field_name not in self.form_data():
             initial_data = self.form_data()
             initial_data[field_name] = None
             self.set_form_data(initial_data)

        attrs = {
            "value": lambda: self.form_data().get(field_name, ''),
        }

        if self.schema.fields.get(field_name).validation_strategy == "onblur":
            attrs["@blur"] = self.handle_blur(field_name)
        else:
            attrs["@input"] = self.handle_change(field_name, debounce_ms)
            
        return attrs

    def handle_submit(self, submit_func: Callable, validate_async: bool = True) -> None:
        """
        Handles form submission.
        
        Args:
            submit_func: The function to call if validation succeeds
            validate_async: Whether to use async validation
        """
        all_fields = list(self.schema.fields.keys())
        touched_updates = {field: True for field in all_fields}
        self.set_touched({**self.touched(), **touched_updates})

        self.set_is_submitting(True)
        
        def on_validation_complete(is_valid):
            try:
                if is_valid:
                    # Pass the potentially trimmed, validated data to the submit function
                    submit_func(self.form_data())
                else:
                    print("Form validation failed on submit:", self.errors())
            finally:
                self.set_is_submitting(False)
        
        # Run validation and handle the result
        if validate_async:
            validation_result = self.validate_form(async_mode=True)
            
            # Set up callback for when async validation completes
            def done_callback(future):
                try:
                    is_valid = future.result()
                    on_validation_complete(is_valid)
                except Exception as e:
                    print(f"Error in async validation: {e}")
                    self.set_is_submitting(False)
                    
            validation_result.add_done_callback(done_callback)
        else:
            # Synchronous validation
            is_valid = self.validate_form(async_mode=False)
            on_validation_complete(is_valid)

    def reset(self, new_initial_values: Optional[Dict[str, Any]] = None) -> None:
        """
        Resets the form to its initial or specified state.
        
        Args:
            new_initial_values: If provided, reset to these values instead of original initial values
        """
        if new_initial_values is not None:
            self.initial_values = deepcopy(new_initial_values)
        
        # Cancel any pending debounce timers
        for timer in self.debounce_timers.values():
            timer.cancel()
        self.debounce_timers = {}
        
        # Reset all form state
        batch_updates(lambda: [
            self.set_form_data(deepcopy(self.initial_values)),
            self.set_errors({}),
            self.set_touched({}),
            self.set_dirty({}),
            self.set_is_submitting(False),
            self.set_meta({
                "is_valid": True,
                "is_dirty": False,
                "is_touched": False,
                "validated_at": None
            })
        ])
        
    def reset_field(self, field_name: str) -> None:
        """
        Resets a single field to its initial value.
        
        Args:
            field_name: The name of the field to reset
        """
        # Cancel any pending debounce timer for this field
        if field_name in self.debounce_timers:
            self.debounce_timers[field_name].cancel()
            del self.debounce_timers[field_name]
        
        def perform_updates():
            current_data = self.form_data()
            current_touched = self.touched()
            current_dirty = self.dirty()
            current_errors = self.errors()
            
            # Reset to initial value
            initial_value = self.initial_values.get(field_name)
            
            # Update form data
            self.set_form_data({**current_data, field_name: initial_value})
            
            # Clear field state
            new_touched = {k: v for k, v in current_touched.items() if k != field_name}
            new_dirty = {k: v for k, v in current_dirty.items() if k != field_name}
            new_errors = {k: v for k, v in current_errors.items() if k != field_name}
            
            self.set_touched(new_touched)
            self.set_dirty(new_dirty)
            self.set_errors(new_errors)
            
            # Update meta state
            self._update_meta_state()
            
        batch_updates(perform_updates)

    def is_valid(self) -> bool:
        """Checks if the entire form is currently valid."""
        return not self.errors()

    def is_field_valid(self, field_name: str) -> bool:
        """Checks if a specific field is valid."""
        return field_name not in self.errors()

    def get_field_errors(self, field_name: str) -> List[str]:
        """Returns all errors for a specific field."""
        return self.errors().get(field_name, [])

    def is_field_dirty(self, field_name: str) -> bool:
        """Checks if a field has been modified from its initial value."""
        return self.dirty().get(field_name, False)
        
    def is_field_touched(self, field_name: str) -> bool:
        """Checks if a field has been touched/interacted with."""
        return self.touched().get(field_name, False)

    def is_fields_valid(self, fields: List[str]) -> Signal:
        """
        Returns a derived signal indicating if the specified fields are currently valid
        based on the errors signal.
        """
        self.validate_form()

        def compute_validity(current_errors: Dict[str, List[str]]) -> bool:
            for field_name in fields:
                if field_name in current_errors and current_errors[field_name]:
                    return False
            return True

        derived_signal, _ = create_derived(self.errors, compute_fn=compute_validity)
        return derived_signal
        
    def get_field_meta(self, field_name: str) -> Dict[str, Any]:
        """
        Returns a dictionary of meta information about a field.
        
        Returns:
            Dictionary with keys:
            - valid: bool - True if the field has no errors
            - errors: List[str] - List of error messages for the field
            - touched: bool - True if the field has been interacted with
            - dirty: bool - True if the field has been modified
        """
        current_errors = self.errors()
        
        return {
            "is_valid": field_name not in current_errors,
            "errors": current_errors.get(field_name, []),
            "is_touched": self.touched().get(field_name, False),
            "is_dirty": self.dirty().get(field_name, False)
        }
        
    def get_nested_value(self, path: str) -> Any:
        """
        Gets a value from the form data using a dotted path notation for nested objects.
        
        Args:
            path: Dotted path to the value, e.g. "user.address.street"
        """
        parts = path.split('.')
        value = self.form_data()
        
        for part in parts:
            # Handle array indexing
            if '[' in part and part.endswith(']'):
                field_name, index_str = part.split('[', 1)
                index = int(index_str[:-1])  # Remove the closing ']'
                
                if not value or field_name not in value:
                    return None
                    
                array_value = value[field_name]
                if not isinstance(array_value, list) or index >= len(array_value):
                    return None
                    
                value = array_value[index]
            else:
                if not value or part not in value:
                    return None
                value = value[part]
                
        return value
        
    def set_nested_value(self, path: str, new_value: Any) -> None:
        """
        Sets a value in the form data using a dotted path notation for nested objects.
        
        Args:
            path: Dotted path to the value, e.g. "user.address.street"
            new_value: The value to set
        """
        parts = path.split('.')
        
        # Create a deep copy to avoid mutating the original
        updated_data = deepcopy(self.form_data())
        
        # Navigate to the right place
        current = updated_data
        for i, part in enumerate(parts[:-1]):  # All but the last part
            # Handle array indexing
            if '[' in part and part.endswith(']'):
                field_name, index_str = part.split('[', 1)
                index = int(index_str[:-1])  # Remove the closing ']'
                
                # Ensure the field exists
                if field_name not in current:
                    current[field_name] = []
                    
                # Ensure the array is long enough
                array_value = current[field_name]
                while len(array_value) <= index:
                    array_value.append({})
                    
                # Move to the next level
                current = array_value[index]
            else:
                # Create the object if it doesn't exist
                if part not in current:
                    current[part] = {}
                current = current[part]
        
        # Set the value at the final location
        last_part = parts[-1]
        
        # Handle array indexing in the last part
        if '[' in last_part and last_part.endswith(']'):
            field_name, index_str = last_part.split('[', 1)
            index = int(index_str[:-1])  # Remove the closing ']'
            
            # Ensure the field exists
            if field_name not in current:
                current[field_name] = []
                
            # Ensure the array is long enough
            array_value = current[field_name]
            while len(array_value) <= index:
                array_value.append(None)
                
            # Set the value
            array_value[index] = new_value
        else:
            current[last_part] = new_value
            
        # Update the form data
        self.set_form_data(updated_data)
        
        # Mark as dirty
        self.set_dirty({**self.dirty(), path: True})
        
        # Validate if using "onchange" strategy
        field_schema = self.schema.fields.get(path)
        validation_strategy = field_schema.validation_strategy if field_schema else self.validation_strategy
        if validation_strategy == "onchange":
            self.validate_field(path, new_value)


def create_form(form_schema: Schema, initial_values: Optional[Dict[str, Any]] = None,
                            validation_strategy: str = "onchange", **kwargs) -> Form:
    """
    Factory function to create and initialize a Form instance.

    Args:
        form_schema: The schema defining the form fields and validation rules.
        initial_values: Optional dictionary of initial values. These values take
                        precedence over any `.initial_value()` set in the schema.
        validation_strategy: Default validation strategy for fields - "onchange",
                             "onblur", or "onsubmit". Can be overridden per field.

    Returns:
        A configured Form instance.
    """
    processed_values = {}
    provided_values = initial_values or {}

    # 1. Apply schema-defined initial values recursively
    def resolve_initial_values(schema: Schema, provided: Dict[str, Any]) -> Dict[str, Any]:
        result = {}
        
        # Handle regular fields
        for field_name, field_schema in schema.fields.items():
            value = _UNSET
            
            # Check provided values first
            if field_name in provided:
                value = provided[field_name]
            # Then check schema default
            elif field_schema.has_default:
                value = field_schema.default_value_attr
            
            # Apply trimming if value is found and is a string
            if value is not _UNSET and field_schema.trim_flag and isinstance(value, str):
                value = value.strip()
                
            if value is not _UNSET:
                result[field_name] = value
            elif not field_schema.optional_flag:
                 # Default to None for required/nullable fields if no value provided
                result[field_name] = None

        # Handle nested schemas
        for nested_name, nested_schema in schema.nested_schemas.items():
            nested_provided = provided.get(nested_name, {})
            # If provided value is None (and nullable), allow it. 
            # But here we assume we want to construct the object structure.
            if nested_provided is None: 
                 result[nested_name] = None
            else:
                result[nested_name] = resolve_initial_values(nested_schema, nested_provided)
                
        # Handle field arrays
        for array_name, field_array in schema.field_arrays.items():
            array_provided = provided.get(array_name)
            
            if array_provided is None:
                # If explicitly None or not provided, defaulting to empty list or None based on requirements
                # Usually arrays default to empty list if not nullable.
                # For now, let's look for a default on the array itself if we added one (we didn't yet in Schema)
                # Or just default to []
                if array_name in provided and array_provided is None:
                     result[array_name] = None
                else:
                     result[array_name] = []
            else:
                # If provided, we need to process items if they are dicts against the item_schema
                # But since arrays are dynamic, we mostly just take the provided values.
                # Optionally we could apply defaults to *items* in the provided array if they are partial objects?
                # For simplicity, we assume provided array items are "complete enough" or will be validated later.
                # However, we SHOULD recurse if the array items are objects to ensure defaults within them are set.
                 processed_array = []
                 for item in array_provided:
                     if isinstance(item, dict):
                         processed_array.append(resolve_initial_values(field_array.item_schema, item))
                     else:
                         processed_array.append(item)
                 result[array_name] = processed_array

        return result

    processed_values = resolve_initial_values(form_schema, provided_values)


    form = Form(processed_values, form_schema)
    form.validation_strategy = validation_strategy # Set default strategy for the form
    return form

