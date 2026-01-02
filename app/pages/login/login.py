from js import console
from metafor.hooks import create_memo, create_signal
from metafor.dom import t, load_css
from metafor.decorators import page, component

from app_state import container, app_provider
from metafor.hooks import use_provider
from metafor.utils import run_async
from metafor.form import  create_form
from metafor.form.schema import Schema
from services import do_auth

@component()
def LoginForm(router, **props):

    auth_error, set_auth_error = create_signal(None)
    # Define the form schema
    form_schema = Schema()
   
    form_schema.field('email').string().email().required().trim()
    form_schema.field('password').string().required().trim().min_length(1)
    form_schema.field('remember_me').bool().required().default_value(False)

    # form_schema.field("age").int().min_value(18, "Must be 18 or older.").max_value(120, "Must be less than 120.")
    # form_schema.field("name").string().required("Name is required.").min_length(3, "Name must be at least 3 characters.")
    
    # Create the form instance
    form = create_form(
        form_schema=form_schema,
        initial_values={"email": "", "password": ""}
    )
    
    form_ref = {}

    # Watch for changes
    app_state, set_state = use_provider(container, app_provider)

    is_enabled = create_memo(lambda: not form.field("email").is_empty and not form.field("password").is_empty)

    def auth_success(response):
        set_state({"auth_user": response})
        router.go("/")

    def auth_fail(error):
        print(f"Authenticate fail: {error}")
        set_auth_error(error.original_error.response.get("data").error)

    def on_field_change(event):
        set_auth_error(None)
    
    def submit_form(data):
        set_auth_error(None)

        if form.is_valid():
            run_async(
                do_auth,
                kwargs=data,
                on_success=auth_success,
                on_error=auth_fail
            )

    show_error = create_memo(lambda:  auth_error()[0].upper() + auth_error()[1:] if auth_error() else '')
    
    return t.form({"ref": form_ref, "@submit": lambda e: [e.preventDefault(), form.handle_submit(submit_form)]}, [
        
        t.p({'class_name': 'error-msg'}, lambda: show_error()),
        
        t.sl_input({
                # "value": username,
                **form.bind_input("email"),
                "@keydown": on_field_change,
                "type": "email",
                "size": "medium",
                "required": True,
                "placeholder": "Email",
                "autocomplete": "off"
            }, [
            t.sl_icon({"name": "person-fill", "slot": "prefix"})
        ]),

        t.sl_input({
                # "value": password,
                # "@input": lambda e: set_password(e.target.value),
                **form.bind_input("password"),
                "@keypress": on_field_change,   
                "type": "password", 
                "size": "medium",
                "placeholder": "Password",
            }, [
            t.sl_icon({"name": "lock-fill", "slot": "prefix"})
        ]),

        t.sl_button({
            "type": "submit",
            "disabled": lambda: not is_enabled(),
            # "disabled": lambda: not form.is_valid(),
            "size": "large",
            "class_name": "login-btn",
            }, "Sign In"),

        t.div({"class_name": "ip-holder"}, [
            t.a({}, "Forgot Password?")
        ]),

        t.div({"class_name": "ip-holder"}, [
            t.a({}, "Create Account")
        ])
    ])


@page("/login")
def Login(**props):
    login_styles = load_css(css_path="login.css")

    return t.div({"class_name": "login-page"}, [
        t.div({"class_name": "inner-page"}, [
            t.div({"class_name": "login-container"}, [
                t.div({"class_name": "logo-holder"}, [
                    t.img({"class_name": "logo", "src": "assets/logo.svg"})
                ]),

                t.h2({}, "Wocom Account Login"),

                LoginForm(**props)
            ])
        ])
       
    ], css=[{"scoped": login_styles}])