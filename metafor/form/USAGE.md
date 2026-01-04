# Metafor Form Library Usage Guide

The `metafor/form` library provides a robust, reactive form management system with schema validation, nested structures, and asynchronous support.

## Table of Contents
1. [Basic Usage](#basic-usage)
2. [Schema Definition](#schema-definition)
3. [Nested Forms](#nested-forms)
4. [Field Arrays](#field-arrays)
5. [Validation](#validation)
    - [Built-in Validators](#built-in-validators)
    - [Cross-Field Validation](#cross-field-validation)
    - [Async Validation](#async-validation)
6. [Form State & Binding](#form-state--binding)

---

## Basic Usage

To create a form, define a `Schema` and initialize it with `create_form`.

```python
from metafor.form.schema import Schema, Field
from metafor.form.form import create_form
from metafor.form.validator import Validator

# 1. Define Schema
user_schema = Schema(
    fields={
        "username": Field(label="Username", validators=[Validator.required(), Validator.min_length(3)]),
        "email": Field(label="Email", validators=[Validator.required(), Validator.email()]),
    }
)

# 2. Create Form
form = create_form(user_schema, initial_values={"username": "guest"})

# 3. Access State (Signal-based)
print(form.form_data()) # {'username': 'guest', 'email': None}
print(form.valid())     # False (email is required)

# 4. Modify Data
form.field("email").set_value("user@example.com")
print(form.valid())     # True
```

## Schema Definition

Schemas define the structure and validation rules for your data.

### Fields
`Field` defines a single data point.

```python
Field(
    label="Age",
    validators=[Validator.min(18)],
    trim=True,             # Auto-trim string values
    optional=False,        # Default is False (Required)
    has_default=True,
    default_value=18
)
```

### Nested Forms
Use `nested_schemas` to group related data.

```python
address_schema = Schema(
    fields={
        "street": Field(label="Street", validators=[Validator.required()]),
        "city": Field(label="City")
    }
)

main_schema = Schema(
    fields={"name": Field(label="Name")},
    nested_schemas={
        "address": address_schema  # Data structure: { "name": ..., "address": { "street": ... } }
    }
)

form = create_form(main_schema)
street_field = form.field("address.street")
street_field.set_value("123 Main St")
```

### Field Arrays
Use `field_arrays` for dynamic lists of items.

```python
item_schema = Schema(fields={"name": Field(label="Item Name")})

order_schema = Schema(
    fields={"order_id": Field(label="ID")},
    field_arrays={
        "items": FieldArray(item_schema=item_schema)
    }
)

form = create_form(order_schema, initial_values={
    "items": [{"name": "Apple"}, {"name": "Banana"}]
})

# Accessing array items
first_item_name = form.field("items[0].name")
```

## Validation

### Built-in Validators
The `Validator` class provides common rules:
- `required()`
- `min_length(n)`, `max_length(n)`
- `min(n)`, `max(n)`
- `email()`
- `regex(pattern)`

### Cross-Field Validation
Validate relationships between multiple fields using `Schema.add_validator`.

```python
def validate_passwords(data, errors):
    if data.get("password") != data.get("confirm_password"):
        return "Passwords do not match"
    return None

schema = Schema(fields={
    "password": Field(validators=[Validator.required()]),
    "confirm_password": Field(validators=[Validator.required()])
})

# Register the validator
schema.add_validator(Validator.cross_field(validate_passwords))
```

### Async Validation
Pass async functions to `async_validators`.

```python
async def check_username_available(value):
    is_taken = await api.check_username(value)
    return "Username taken" if is_taken else None

Field(
    validators=[Validator.required()],
    async_validators=[check_username_available]
)
```

## Form State & Binding

The `Form` class exposes reactive signals for UI Integration.

### Core Signals
- `form.form_data()`: The current data dictionary.
- `form.errors()`: Dictionary of errors `{ field_path: [errors] }`.
- `form.touched()`: Fields that have been blurred `{ field_path: True }`.
- `form.dirty()`: Fields changed from initial `{ field_path: True }`.
- `form.valid()`: Boolean, true if no errors exist.

### Field Handle & Clean API
Get a handle for easier binding using `form.field(path)` or the cleaner `form.F` proxy:

```python
# Standard String Access
field = form.field("user.email")

# Clean Proxy Access (Recommended)
field = form.F.user.email
name_field = form.F.items[0].name
```

**Field Properties (via `.meta`)**:
When using the handle, you can access state directly:

```python
field.value          # Get current value
field.set_value(val) # Set value
field.valid          # bool
field.error          # First error string or None
field.touched        # bool
```

### UI Binding
Use `bind_input` to get props for valid HTML/Component inputs.

```python
# Returns {'value': ..., '@input': ...}
props = form.bind_input("username", validation_options={"debounce_ms": 300})
```

## Submission
Use `handle_submit` to wrap your submit logic with validation.

```python
def on_submit(valid_data):
    print("Saving:", valid_data)

# Validates form (sync & async) before calling on_submit
form.handle_submit(on_submit)
```
