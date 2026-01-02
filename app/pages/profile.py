from js import console
from typing import Any, Optional
from types import FunctionType
from metafor.core import Signal, batch_updates, on_mount
from metafor.hooks import use_context, create_memo
from metafor.core import create_effect, create_signal
from metafor.dom import t
from metafor.decorators import page, component
from metafor.utils import run_async

from contexts import ThemeContext
from services import fetch_user

@component(props={"profile": Signal, "handle_name": Any, "handle_age": FunctionType})
def Me(**props):
    profile = props["profile"]
    
    return t.div({}, [
        t.p({}, [
            "Name: ",
            lambda: profile()["name"]
        ]),
        
        t.p({}, [
            "Age: ",
            lambda: profile()["age"]
        ]),
        
        t.p({}, [
            "City: ",
            lambda: profile()["city"]
        ]),
        
        t.button({"class_name": "btn btn-secondary me-2", "onclick": props['handle_name']}, "Update Name and City"),
        t.button({"class_name": "btn btn-secondary", "onclick": props['handle_age']}, "Update Age")
    ])

@page("/profile")
def ProfileLayout(children, **props):
    
    return t.div({}, [
        children
    ])
  
# Profile Component
@page("", props={})
def Profile(**props):
    t.page_title("Profile Page")
    
    print(props)
    
    theme = use_context(ThemeContext)

    # Create a signal holding a profile object
    profile, set_profile = create_signal({
        "age": 30,
        "name": "Ricardo",
        "city": "New York"
    })

    name = create_memo(lambda: profile()["name"])

    print(name())

    # Create a function to update profile data
    def update_profile(new_name=None, new_age=None, new_city=None):
        current_profile = profile()
        
        batch_updates(lambda: [
            set_profile({
                "name": new_name if new_name is not None else current_profile["name"],
                "age": new_age if new_age is not None else current_profile["age"],
                "city": new_city if new_city is not None else current_profile["city"]
            })
        ])

    # Example of reacting to property changes
    def log_name():
        print(f"Name changed to: { profile()['name'] }")
    
    def log_age():
        print(f"Age changed to: { profile()['age'] }")
    
    def log_city():
        print(f"City changed to: { profile()['city'] }")
    
    create_effect(log_name)
    create_effect(log_age)
    create_effect(log_city)
        
    def handle_update_profile(evt):
        update_profile(new_name='John', new_city='London')

    def handle_update_age(evt):
        update_profile(new_age=35)

    def on_success(result):
        console.log(result)
        set_profile({
            "name": result.firstName + " " + result.lastName,
            "age": 33,
            "city": "Old Harbour"
        })
        
        console.log(f"Task result: {result}")

    def on_error(error):
        print(f"Task error: {error}")

    def did_mount():
        run_async(
            fetch_user,
            on_success=on_success,
            on_error=on_error
        )

    on_mount(did_mount)

    return t.div({"class_name": lambda: f"profile theme-{theme()}" }, [
        t.h3({}, "Profile"),
        
        Me(
            profile = profile,
            handle_age = handle_update_age,
            handle_name = handle_update_profile
        ),
    ])