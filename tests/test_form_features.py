import asyncio
import sys
import os

# Ensure we can import the package
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../')))

# MOCK ENVIRONMENT setup must happen BEFORE importing metafor
from unittest.mock import MagicMock
if 'js' not in sys.modules:
    js_mock = MagicMock()
    js_mock.document = MagicMock()
    js_mock.console = MagicMock()
    js_mock.setTimeout = MagicMock()
    sys.modules['js'] = js_mock

if 'pyodide' not in sys.modules:
    sys.modules['pyodide'] = MagicMock()
if 'pyodide.ffi' not in sys.modules:
    pyodide_ffi_mock = MagicMock()
    pyodide_ffi_mock.create_proxy = MagicMock(side_effect=lambda x: x)
    pyodide_ffi_mock.JsProxy = MagicMock
    sys.modules['pyodide.ffi'] = pyodide_ffi_mock

print("Environment mocked inline.")

from metafor.form.form import create_form, Form
from metafor.form.schema import Schema

def test_deep_initial_values():
    print("Testing Deep Initial Values...")
    schema = Schema()
    schema.field("name").string()
    
    nested = schema.nested("config")
    nested.field("theme").string().default_value("dark")
    nested.field("notifications").bool().default_value(True)
    
    # Test 1: Defaults only
    form = create_form(schema)
    data = form.form_data()
    assert data["name"] is None
    assert data["config"]["theme"] == "dark"
    assert data["config"]["notifications"] is True
    print("  ✓ Defaults resolved correctly")

    # Test 2: Overrides
    form = create_form(schema, initial_values={"config": {"theme": "light"}})
    data = form.form_data()
    assert data["config"]["theme"] == "light"
    assert data["config"]["notifications"] is True # Should still be default
    print("  ✓ Overrides work correctly")

def test_nested_array_defaults():
    print("Testing Nested Array Defaults...")
    schema = Schema()
    
    item_schema = Schema()
    item_schema.field("id").int()
    item_schema.field("active").bool().default_value(False)
    
    schema.array("items", item_schema)
    
    # Test: Array of partial objects
    initial = {
        "items": [
            {"id": 1}, # active should be False
            {"id": 2, "active": True}
        ]
    }
    
    form = create_form(schema, initial_values=initial)
    data = form.form_data()
    
    assert data["items"][0]["active"] is False
    assert data["items"][1]["active"] is True
    print("  ✓ Array item defaults resolved")

def test_nested_field_validation():
    print("Testing Nested Field Validation...")
    schema = Schema()
    nested = schema.nested("user")
    nested.field("email").string().email()
    
    form = create_form(schema, initial_values={"user": {"email": "invalid"}})
    
    # Trigger validation on specific nested field
    # This exercises the "optimization" path in form.validate_field
    field = form.field("user.email")
    field.set_value("bad-email")
    
    assert not field.meta.valid
    assert field.meta.error == "Must be a valid email address."
    print("  ✓ Nested field validation detected error")
    
    field.set_value("good@example.com")
    assert field.meta.valid
    print("  ✓ Nested field validation cleared error")

def test_cross_field_validation():
    print("Testing Cross-Field Validation...")
    schema = Schema()
    schema.field("password").string()
    schema.field("confirm_password").string()
    
    def passwords_match(data):
        if data.get("password") != data.get("confirm_password"):
            return {"confirm_password": ["Passwords do not match"]}
        return None
        
    schema.add_validator(passwords_match)
    
    form = create_form(schema, initial_values={"password": "abc", "confirm_password": "xyz"})
    
    # Trigger full validation (cross validators run on full validation or usually when fields change if we wired it up)
    # Note: Our implementation runs cross validators in `schema.validate()`, which is called by `form.validate_form()`
    # Does `field check` trigger it? 
    # form.validate_field calls field_schema.validation_functions. It does NOT call schema level cross validators.
    # So we need to call validate_form() to see cross errors.
    
    valid = form.validate_form()
    assert not valid
    errors = form.errors()
    assert "confirm_password" in errors
    assert "Passwords do not match" in errors["confirm_password"]
    print("  ✓ Cross-validators detected error")
    
    form.set_form_data({"password": "abc", "confirm_password": "abc"})
    valid = form.validate_form()
    assert valid
    print("  ✓ Cross-validators passed")

def test_clean_api():
    print("Testing Clean API (FieldAccessProxy)...")
    schema = Schema()
    
    # Nested fields
    nested = schema.nested("user")
    nested.field("email").string().email()
    
    # Nested arrays
    item_schema = Schema()
    item_schema.field("name").string()
    schema.array("items", item_schema)
    
    form = create_form(schema, initial_values={
        "user": {"email": "test@example.com"},
        "items": [{"name": "Item 1"}, {"name": "Item 2"}]
    })
    
    # 1. Test Dot Syntax for Nested Fields
    # Instead of form.field("user.email").value()
    assert form.F.user.email.value == "test@example.com"
    print("  ✓ Dot syntax works: form.F.user.email")
    
    # 2. Test Array Index Syntax
    # Instead of form.field("items[0].name").value()
    assert form.F.items[0].name.value == "Item 1"
    assert form.F.items[1].name.value == "Item 2"
    print("  ✓ Array syntax works: form.F.items[0]")
    
    # 3. Test Mixed/Bracket Syntax for string keys (optional but supported)
    assert form.F['user']['email'].value == "test@example.com"
    print("  ✓ Bracket syntax works: form.F['user']['email']")
    
    # 4. Test Write Access
    form.F.user.email.set_value("new@example.com")
    assert form.F.user.email.value == "new@example.com"
    assert form.F.user.email.valid
    print("  ✓ Write access works")
    
    # 5. Test Metadata Access
    form.F.user.email.set_value("invalid-email")
    assert not form.F.user.email.valid
    assert form.F.user.email.error == "Must be a valid email address."
    print("  ✓ Validation metadata works")

def run_tests():
    try:
        test_deep_initial_values()
        test_nested_array_defaults()
        test_nested_field_validation()
        test_cross_field_validation()
        test_clean_api()
        print("\nAll tests passed!")
    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    run_tests()
