# /Users/ricardo/metafor/metafor/form/schema.py
from typing import Dict, Any, Callable, Optional, List, Union, TypeVar, Type, Set, cast
import re
from datetime import date as Date
from uuid import UUID as PyUUID
import asyncio
from functools import partial

from metafor.core import batch_updates, create_signal
from metafor.form.validator import Validator


T = TypeVar('T')
_UNSET = object() # Sentinel object to differentiate unset initial value from None initial value

class Field:
    """
    Represents a single field in a form schema.
    """
    def __init__(self):
        self.type: Union[type, str] = None
        self.required_flag: bool = False
        self.optional_flag: bool = False
        self.nullable_flag: bool = False
        self.trim_flag: bool = False
        self.validation_functions: List[Callable[[Any], Optional[str]]] = []
        self.async_validation_functions: List[Callable[[Any], Any]] = []
        self.conditional_validation: Optional[Callable[[Dict[str, Any]], bool]] = None
        self.validation_strategy: str = "onchange"  # Options: onchange, onblur, onsubmit
        self.dependent_fields: Set[str] = set()
        
        self.field_path: Optional[str] = None  # For nested fields
        self.default_value_attr: Any = _UNSET # Use sentinel
        self.required_message: str = "This field is required."
        
    # -- Primitives ---
    def string(self) -> 'Field':
        """Sets the field type to string."""
        self.type = str
        return self

    def int(self) -> 'Field':
        """Sets the field type to integer."""
        self.type = int
        return self

    def float(self) -> 'Field':
        """Sets the field type to float."""
        self.type = float
        return self

    def bool(self) -> 'Field':
        """Sets the field type to boolean."""
        self.type = bool
        return self

    def list(self) -> 'Field':
        """Sets the field type to list."""
        self.type = list
        return self

    def dict(self) -> 'Field':
        """Sets the field type to dictionary."""
        self.type = dict
        return self

    def date(self) -> 'Field':
        """Sets the field type to date."""
        self.type = "date"
        return self

    def time(self) -> 'Field':
        """Sets the field type to time."""
        self.type = "time"
        return self

    def datetime(self) -> 'Field':
        """Sets the field type to datetime."""
        self.type = "datetime"
        return self
        
        
    # -- End Primitives ---

    def trim(self) -> 'Field':
        """Marks the field to have its value trimmed before validation and storage."""
        self.trim_flag = True
        return self

    def required(self, error_message: str = "This field is required.") -> 'Field':
        """
        Marks the field as required.
        - It must be present in the data.
        - It cannot be None unless `.nullable()` is also used.
        - It cannot be an empty string/list/dict unless `.nullable()` is used (and the value is None).
        - This is ignored if `.optional()` is used.
        """
        self.required_flag = True
        self.optional_flag = False # Required overrides optional
        self.required_message = error_message
        # The actual validation check happens in Schema.validate based on flags
        return self
        
    def optional(self) -> 'Field':
        """
        Marks the field as optional.
        - It does not need to be present in the data.
        - If present, it will still be validated against other rules.
        - Overrides `.required()`.
        """
        self.optional_flag = True
        self.required_flag = False # Optional overrides required
        return self
    
    def nullable(self) -> 'Field':
        """
        Allows `None` as a valid value for this field.
        - If used with `.required()`, the field must be present, but can be `None`.
        - If used without `.required()` (or with `.optional()`), the field can be absent OR `None`.
        - Other validation rules (like min_length, email) will be skipped if the value is `None`.
        """
        self.nullable_flag = True
        return self
        
    def default_value(self, value: Any) -> 'Field':
        """
        Sets a default initial value for this field in the schema.
        This will be used by `create_form` unless overridden by the
        `initial_values` dictionary passed to the factory.
        """
        self.default_value_attr = value
        return self
    
    @property
    def has_default(self) -> bool:
        """Checks if an initial value was explicitly set (even if it's None)."""
        return self.default_value_attr is not _UNSET
    
    def bool(self, error_message: str = "Must be a boolean (true or false).") -> 'Field':
        """Sets the field type to boolean and adds boolean validation."""
        self.type = bool
        # Add the boolean validator, considering the nullable status
        # We wrap it in a lambda to pass the current nullable_flag state
        # when the validation actually runs.
        self.validation_functions.append(
            lambda value: Validator.boolean(value, error_message, allow_none=self.nullable_flag)
        )
        return self

    def min_length(self, length: int, error_message: str = None) -> 'Field':
        """Adds a minimum length validation."""
        self.validation_functions.append(Validator.min_length(length, error_message))
        return self

    def max_length(self, length: int, error_message: str = None) -> 'Field':
        """Adds a maximum length validation."""
        self.validation_functions.append(Validator.max_length(length, error_message))
        return self

    def email(self, error_message: str = "Must be a valid email address.") -> 'Field':
        """Adds an email validation."""
        self.validation_functions.append(lambda value: Validator.email(value, error_message))
        return self

    def url(self, error_message: str = "Must be a valid URL.") -> 'Field':
        """Adds a URL validation."""
        self.validation_functions.append(lambda value: Validator.url(value, error_message))
        return self

    def phone(self, pattern: str = None, error_message: str = "Must be a valid phone number.") -> 'Field':
        """Adds phone number validation."""
        self.validation_functions.append(lambda value: Validator.phone(value, pattern, error_message))
        return self

    def uuid(self, error_message: str = "Must be a valid UUID.") -> 'Field':
        """Adds UUID validation."""
        self.validation_functions.append(lambda value: Validator.uuid(value, error_message))
        return self

    def regex(self, pattern: str, error_message: str = "Invalid format.") -> 'Field':
        """Adds a regex validation."""
        self.validation_functions.append(Validator.regex(pattern, error_message))
        return self

    def min_value(self, min_val: Union[int, float], error_message: str = None) -> 'Field':
        """Adds a minimum value validation."""
        self.validation_functions.append(Validator.min_value(min_val, error_message))
        return self

    def max_value(self, max_val: Union[int, float], error_message: str = None) -> 'Field':
        """Adds a maximum value validation."""
        self.validation_functions.append(Validator.max_value(max_val, error_message))
        return self

    def date_min(self, min_date: Union[str, Date], error_message: str = None) -> 'Field':
        """Adds a minimum date validation."""
        self.validation_functions.append(Validator.date_min(min_date, error_message))
        return self

    def date_max(self, max_date: Union[str, Date], error_message: str = None) -> 'Field':
        """Adds a maximum date validation."""
        self.validation_functions.append(Validator.date_max(max_date, error_message))
        return self

    def custom(self, validation_func: Callable[[Any], Optional[str]]) -> 'Field':
        """Adds a custom validation function."""
        self.validation_functions.append(Validator.custom(validation_func))
        return self

    def async_validator(self, validation_func: Callable[[Any], Any]) -> 'Field':
        """Adds an asynchronous validation function that returns a coroutine."""
        self.async_validation_functions.append(validation_func)
        return self

    def matches(self, field_name: str, error_message: str = "Fields must match.") -> 'Field':
        """
        Ensures this field matches another field's value.
        Validation occurs during Schema validation where form_data is available.
        """
        self.field_path = field_name
        self.match_error_message = error_message
        # No validator function added here; handled directly in Schema.validate
        return self

    def when(self, condition: Callable[[Dict[str, Any]], bool]) -> 'Field':
        """Sets a condition for when this field should be validated."""
        self.conditional_validation = condition
        return self

    def validate_on(self, strategy: str) -> 'Field':
        """Sets when validation should occur for this field."""
        valid_strategies = ["onchange", "onblur", "onsubmit"]
        if strategy not in valid_strategies:
            raise ValueError(f"Strategy must be one of: {', '.join(valid_strategies)}")
        self.validation_strategy = strategy
        return self


class FieldArray:
    """Represents an array of fields in a form schema."""
    def __init__(self, item_schema: 'Schema'):
        self.item_schema = item_schema
        self.min_length: Optional[int] = None
        self.max_length: Optional[int] = None
        self.validation_functions: List[Callable[[List[Any]], Optional[str]]] = []

    def min_items(self, min_count: int, error_message: str = None) -> 'FieldArray':
        """Sets minimum number of items required."""
        self.min_length = min_count
        error_msg = error_message or f"Must have at least {min_count} items."
        self.validation_functions.append(lambda items: error_msg if items is None or len(items) < min_count else None)
        return self

    def max_items(self, max_count: int, error_message: str = None) -> 'FieldArray':
        """Sets maximum number of items allowed."""
        self.max_length = max_count
        error_msg = error_message or f"Must have at most {max_count} items."
        self.validation_functions.append(lambda items: error_msg if items is not None and len(items) > max_count else None)
        return self

    def custom(self, validation_func: Callable[[List[Any]], Optional[str]]) -> 'FieldArray':
        """Adds a custom validation function for the entire array."""
        self.validation_functions.append(Validator.custom(validation_func))
        return self


class Schema:
    """
    Defines the schema for a form, including fields and their validation rules.
    """
    def __init__(self):
        self.fields: Dict[str, Field] = {}
        self.nested_schemas: Dict[str, 'Schema'] = {}
        self.field_arrays: Dict[str, FieldArray] = {}

    def field(self, name: str) -> Field:
        """Adds a field to the schema."""
        field = Field()
        field.field_path = name  # Store the field path for nested fields
        self.fields[name] = field
        return field
    
    def __getattr__(self, name: str) -> Field:
        def field() -> Field:
            return self.field(name)
        return field

    def nested(self, name: str) -> 'Schema':
        """Creates a nested schema."""
        nested_schema = Schema()
        self.nested_schemas[name] = nested_schema
        return nested_schema

    def array(self, name: str, item_schema: 'Schema') -> FieldArray:
        """Creates an array of objects with a defined schema."""
        field_array = FieldArray(item_schema)
        self.field_arrays[name] = field_array
        return field_array

    def validate(self, form_data: Dict[str, Any]) -> Dict[str, List[str]]:
        """Validates the form data against the schema."""
        errors: Dict[str, List[str]] = {}
        
        # Validate regular fields
        for field_name, field in self.fields.items():
            field_errors = []
            
            # 1. Check conditional validation
            if field.conditional_validation and not field.conditional_validation(form_data):
                continue # Skip validation for this field
            
            # 2. Get value and apply trimming
            value = form_data.get(field_name, _UNSET) # Use sentinel to detect absence
            
            # Handle optional fields: if absent, skip all validation
            if field.optional_flag and value is _UNSET:
                continue
            
            # Apply trimming if present and applicable
            value = value
            if field.trim_flag and isinstance(value, str):
                value = value.strip()
            
            # 3. Check required status (only if not optional)
            if not field.optional_flag and field.required_flag:
                # Use the updated Validator.required with allow_none flag
                error_message = Validator.required(
                    value if value is not _UNSET else None, # Pass None if absent
                    field.required_message,
                    allow_none=field.nullable_flag
                )
                if error_message:
                    field_errors.append(error_message)
            
            # 4. Handle nullable: If None is allowed and value is None, skip subsequent validators
            is_none_and_nullable = field.nullable_flag and value is None
            if is_none_and_nullable:
                # Add any existing required errors, then skip other checks
                if field_errors:
                    errors[field_name] = field_errors
                continue # Skip min_length, regex etc. for allowed None
            
            # 5. Apply other synchronous validators (only if value is not None or None is not allowed)
            if value is not None and value is not _UNSET:
                 for validation_func in field.validation_functions:
                    # We assume validation_func correctly handles the type or skips None
                    error_message = validation_func(value)
                    if error_message:
                        field_errors.append(error_message)
            
            # 6. Check 'matches' validation
            if field.field_path:
                target_value = form_data.get(field.field_path)
                # Only compare if the current field's value is not None (or None is disallowed)
                # And the target field's value is also not None (common use case)
                # Adjust this logic if None should be comparable
                if value != target_value and value is not None:
                     field_errors.append(field.match_error_message or "Fields must match.")
            
            
            # 7. Store errors for the field
            if field_errors:
                # Use set to remove potential duplicate messages if rules overlap
                errors[field_name] = list(dict.fromkeys(field_errors))
        
        # Validate nested schemas
        for nested_name, nested_schema in self.nested_schemas.items():
            nested_data = form_data.get(nested_name, {})
            if not isinstance(nested_data, dict):
                errors[nested_name] = ["Invalid nested object"]
                continue
                
            nested_errors = nested_schema.validate(nested_data)
            if nested_errors:
                # Prefix nested field errors with the nested object name
                for key, value in nested_errors.items():
                    errors[f"{nested_name}.{key}"] = value
        
        # Validate field arrays
        for array_name, field_array in self.field_arrays.items():
            array_data = form_data.get(array_name, [])
            if not isinstance(array_data, list):
                errors[array_name] = ["Invalid array"]
                continue
                
            # Array-level validations
            array_errors = []
            for validation_func in field_array.validation_functions:
                error_message = validation_func(array_data)
                if error_message:
                    array_errors.append(error_message)
            
            if array_errors:
                errors[array_name] = array_errors
                
            # Item-level validations
            for i, item in enumerate(array_data):
                if not isinstance(item, dict):
                    if array_name not in errors:
                        errors[array_name] = []
                    errors[array_name].append(f"Item at index {i} is not a valid object")
                    continue
                    
                item_errors = field_array.item_schema.validate(item)
                if item_errors:
                    # Prefix item errors with array name and index
                    for key, value in item_errors.items():
                        errors[f"{array_name}[{i}].{key}"] = value
        
        return errors

    async def validate_async(self, form_data: Dict[str, Any]) -> Dict[str, List[str]]:
        """Validates the form data including asynchronous validators."""
        # First, run all synchronous validations
        errors = self.validate(form_data)
        
        # Collect async tasks only for fields that currently have no sync errors
        # and meet async validation criteria (not optional-absent, not nullable-none)
        async_tasks = []
        fields_to_validate_async = []
        
        for field_name, field in self.fields.items():
            # Skip if conditional validation fails
            if field.conditional_validation and not field.conditional_validation(form_data):
                continue
        
            # Skip if field already has synchronous errors
            if field_name in errors:
                continue
        
            # Skip if field is optional and absent
            value = form_data.get(field_name, _UNSET)
            if field.optional_flag and value is _UNSET:
                continue
        
            # Apply trimming
            if field.trim_flag and isinstance(value, str):
                value = value.strip()
        
            # Skip async if field is nullable and value is None
            if field.nullable_flag and value is None:
                continue
        
            # Skip if value is absent and not optional (already handled by sync required check)
            if value is _UNSET and not field.optional_flag:
                continue # Should have sync error unless nullable
        
            # Skip if no async validators defined
            if not field.async_validation_functions:
                continue
        
            # If value is valid so far and has async validators, add tasks
            if value is not None or not field.nullable_flag: # Ensure we don't validate None unless intended
                fields_to_validate_async.append((field_name, field, value))
        
        
        # Create tasks for async validators for eligible fields
        for field_name, field, value_to_validate in fields_to_validate_async:
            for async_validator in field.async_validation_functions:
                # Wrap the validator call to return (field_name, error_message)
                async_tasks.append(self._run_async_validator(field_name, value_to_validate, async_validator))
        
        # Run async validators concurrently
        if async_tasks:
            async_results = await asyncio.gather(*async_tasks, return_exceptions=True)
        
            # Process async validation results, adding errors to the existing dict
            for result in async_results:
                if isinstance(result, Exception):
                    # Handle exceptions during async validation itself
                    # Log this properly, maybe add a generic error?
                    print(f"Async validator exception: {result}")
                    # Decide how to report this - maybe add to a general form error?
                    # errors['_async_error'] = errors.get('_async_error', []) + [f"Internal validation error"]
                elif isinstance(result, tuple) and len(result) == 2:
                    field_name, error_message = result
                    if error_message: # If the validator returned an error string
                        if field_name not in errors:
                            errors[field_name] = []
                        # Avoid duplicates if multiple async validators fail on the same field
                        if error_message not in errors[field_name]:
                            errors[field_name].append(error_message)
        
            
        return errors


    async def _run_async_validator(self, field_name: str, value: Any,
                              validator: Callable[[Any], Any]) -> tuple[str, Optional[str]]:
        """Helper to run a single async validator and handle its result/exceptions."""
        try:
            result = validator(value)
            error_message = None
            if asyncio.iscoroutine(result):
                error_message = await result
            else: # Allow async validators to return non-coroutines (e.g., simple checks)
                error_message = result
        
            # Ensure error_message is None or a string
            if error_message is not None and not isinstance(error_message, str):
                print(f"Warning: Async validator for '{field_name}' returned non-string: {error_message}")
                return field_name, "Invalid validation result." # Return generic error
        
            return field_name, error_message
        except Exception as e:
            print(f"Error executing async validator for '{field_name}': {e}")
            # Return the exception message or a generic error
            return field_name, f"Validation error: {str(e)}"