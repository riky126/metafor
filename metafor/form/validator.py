# /Users/ricardo/metafor/metafor/form/validator.py
from typing import Any, Callable, Optional, Union, Dict, List, cast
import re
import datetime
from uuid import UUID as PyUUID

class Validator:
    """
    Provides a set of built-in validation functions.
    """

    @staticmethod
    def required(value: Any, error_message: str = "This field is required.", allow_none: bool = False) -> Optional[str]:
        """Checks if a value is required, potentially allowing None."""
        if allow_none and value is None:
            return None # Explicitly allowed None passes required check
        return Validator.not_empty(value, error_message, allow_none)
    
    @staticmethod
    def not_empty(value: Any, error_message: str = "This field cannot be empty.", allow_none: bool = False) -> Optional[str]:
        """Checks if a value is not empty, potentially allowing None."""
        if value is None:
            # If None is allowed, it's not considered "empty" for validation purposes
            # If None is *not* allowed, it *is* considered empty.
            return None if allow_none else error_message
    
        # Handle different types (unchanged from original)
        if isinstance(value, (str, list, dict, tuple, set)):
            if not value:  # Empty string, list, dict, tuple, or set
                return error_message
        elif isinstance(value, (int, float)):
            # Consider if 0 should be treated as empty - Zod doesn't by default.
            # Let's remove the 0 check for now to align better.
            # If you need "0 is invalid", use .min_value(1) or similar.
            pass # 0 is a valid value unless other validators prevent it
        elif isinstance(value, bool):
            # Consider if False should be treated as empty - Zod doesn't by default.
            # Let's remove the False check. Required boolean means it must be True or False.
            pass # False is a valid value
    
        return None

    @staticmethod
    def min_length(length: int, error_message: str = None) -> Callable[[str], Optional[str]]:
        """Creates a validation function that checks for minimum length."""
        def validate(value: str) -> Optional[str]:
            # Allow None values to pass, required validator should handle them
            if value is not None and len(str(value)) < length:
                return error_message or f"Must be at least {length} characters long."
            return None
        return validate

    @staticmethod
    def max_length(length: int, error_message: str = None) -> Callable[[str], Optional[str]]:
        """Creates a validation function that checks for maximum length."""
        def validate(value: str) -> Optional[str]:
             # Allow None values to pass
            if value is not None and len(str(value)) > length:
                return error_message or f"Must be at most {length} characters long."
            return None
        return validate
    
    @staticmethod
    def boolean(value: Any, error_message: str = "Must be a boolean (true or false).", allow_none: bool = False) -> Optional[str]:
        """Checks if a value is a boolean (True or False), potentially allowing None."""
        if value is None:
            return None if allow_none else error_message # Fail if None is not allowed

        if not isinstance(value, bool):
            return error_message
        return None

    @staticmethod
    def email(value: str, error_message: str = None) -> Optional[str]:
        """
        Checks if a value is a valid email address using the regex validator.
        """
        # Allow None or empty values to pass; 'required' handles mandatory fields.
        if value is None or value == "":
            return None

        # A commonly used regex for email validation
        email_pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"

        # Create the regex validation function
        regex_validator = Validator.regex(email_pattern, error_message or "Must be a valid email address.")

        # Execute the regex validation
        return regex_validator(value)

    @staticmethod
    def url(value: str, error_message: str = None) -> Optional[str]:
        """
        Checks if a value is a valid URL.
        """
        if value is None or value == "":
            return None

        # URL validation pattern
        url_pattern = r"^https?://(?:www\.)?[-a-zA-Z0-9@:%._+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b(?:[-a-zA-Z0-9()@:%_+.~#?&/=]*)$"
        
        regex_validator = Validator.regex(url_pattern, error_message or "Must be a valid URL.")
        return regex_validator(value)

    @staticmethod
    def phone(value: str, pattern: str = None, error_message: str = None) -> Optional[str]:
        """
        Checks if a value is a valid phone number.
        """
        if value is None or value == "":
            return None

        # Default to a generic international phone pattern if none provided
        phone_pattern = pattern or r"^\+?[0-9]{10,15}$"
        
        regex_validator = Validator.regex(phone_pattern, error_message or "Must be a valid phone number.")
        return regex_validator(value)

    @staticmethod
    def uuid(value: str, error_message: str = None) -> Optional[str]:
        """
        Checks if a value is a valid UUID.
        """
        if value is None or value == "":
            return None

        try:
            PyUUID(value)
            return None
        except (ValueError, AttributeError, TypeError):
            return error_message or "Must be a valid UUID."

    @staticmethod
    def regex(pattern: str, error_message: str = None) -> Callable[[str], Optional[str]]:
        """Creates a validation function that checks against a regex pattern."""
        compiled_pattern = re.compile(pattern)
        def validate(value: str) -> Optional[str]:
            # Allow None values to pass
            if value is not None and not compiled_pattern.fullmatch(str(value)):
                return error_message
            return None
        return validate

    @staticmethod
    def min_value(min_val: Union[int, float], error_message: str = None) -> Callable[[Union[int, float]], Optional[str]]:
        """Creates a validation function that checks for minimum value."""
        def validate(value: Union[int, float]) -> Optional[str]:
             # Allow None values to pass
            if value is not None:
                try:
                    num_value = float(value) # Attempt conversion
                    if num_value < min_val:
                         return error_message or f"Must be at least {min_val}."
                except (ValueError, TypeError):
                     return "Must be a valid number." # Handle non-numeric input
            return None
        return validate

    @staticmethod
    def max_value(max_val: Union[int, float], error_message: str = None) -> Callable[[Union[int, float]], Optional[str]]:
        """Creates a validation function that checks for maximum value."""
        def validate(value: Union[int, float]) -> Optional[str]:
            # Allow None values to pass
            if value is not None:
                try:
                    num_value = float(value) # Attempt conversion
                    if num_value > max_val:
                        return error_message or f"Must be at most {max_val}."
                except (ValueError, TypeError):
                    return "Must be a valid number." # Handle non-numeric input
            return None
        return validate

    @staticmethod
    def date_min(min_date: Union[str, datetime.date], error_message: str = None) -> Callable[[Union[str, datetime.date]], Optional[str]]:
        """Creates a validation function that checks for minimum date."""
        # Convert string to date if necessary
        if isinstance(min_date, str):
            try:
                min_date = datetime.date.fromisoformat(min_date)
            except ValueError:
                raise ValueError(f"Invalid date format: {min_date}. Use ISO format (YYYY-MM-DD).")
        
        def validate(value: Union[str, datetime.date]) -> Optional[str]:
            if value is None or value == "":
                return None
                
            try:
                # Convert value to date if it's a string
                date_value = value
                if isinstance(value, str):
                    date_value = datetime.date.fromisoformat(value)
                
                if date_value < min_date:
                    return error_message or f"Date must be on or after {min_date.isoformat()}."
                return None
            except ValueError:
                return "Invalid date format. Use ISO format (YYYY-MM-DD)."
                
        return validate

    @staticmethod
    def date_max(max_date: Union[str, datetime.date], error_message: str = None) -> Callable[[Union[str, datetime.date]], Optional[str]]:
        """Creates a validation function that checks for maximum date."""
        # Convert string to date if necessary
        if isinstance(max_date, str):
            try:
                max_date = datetime.date.fromisoformat(max_date)
            except ValueError:
                raise ValueError(f"Invalid date format: {max_date}. Use ISO format (YYYY-MM-DD).")
        
        def validate(value: Union[str, datetime.date]) -> Optional[str]:
            if value is None or value == "":
                return None
                
            try:
                # Convert value to date if it's a string
                date_value = value
                if isinstance(value, str):
                    date_value = datetime.date.fromisoformat(value)
                
                if date_value > max_date:
                    return error_message or f"Date must be on or before {max_date.isoformat()}."
                return None
            except ValueError:
                return "Invalid date format. Use ISO format (YYYY-MM-DD)."
                
        return validate

    @staticmethod
    def cross_field(value: Any, cross_validator: Callable[[Any, Dict[str, Any]], Optional[str]]) -> Optional[str]:
        """
        Creates a placeholder for cross-field validation that will be resolved during form validation.
        The actual validation happens in the Form class where the form_data is available.
        """
        # This is a special case - the cross_validator will be used directly
        # by the Form class, which will provide the form_data
        return None

    @staticmethod
    def custom(validation_func: Callable[[Any], Optional[str]]) -> Callable[[Any], Optional[str]]:
        """Allows adding custom validation functions."""
        # Wrap the custom function to handle potential errors gracefully
        def safe_validate(value: Any) -> Optional[str]:
            try:
                return validation_func(value)
            except Exception as e:
                print(f"Error in custom validator: {e}") # Or log more formally
                return "Validation failed due to an internal error."
        return safe_validate