from js import console
from metafor.decorators import page, component, reusable
from metafor.core import batch_updates, create_signal, on_dispose, on_mount
from metafor.dom import load_css, t
from metafor.hooks import create_memo, use_context, create_effect
from metafor.router import  router_delegate
from contexts import DBContext, ThemeContext

from app_state import container, app_provider
from metafor.hooks import use_provider
from metafor.components import For, Show
from metafor.utils import run_async
from services import fetch_account

class SidebarItem:
    def __init__(self, label:str, icon:str, route:str):
        self.label = label
        self.icon = icon
        self.route = route


def sidebar_item(item, index):
    router = router_delegate()

    return t.div({"key": item.route}, [
        t.sl_button({
            "variant": "text",
            "class_name": "sidebar-button",
            "@click": lambda event: router.go(item.route),
            # "href": f"#/{item.route}",
        }, [
            item.label,

            Show(item.icon, lambda: t.sl_icon({"name": item.icon, "slot": "prefix"}))
        ])   
    ])


@component()
def TopbarMenu(**props):
    my_ref = {}
    
    app_state, set_appstate = use_provider(container, app_provider)

    router = router_delegate()

    def on_menu_select(event):
        match event.detail.item.value:
            case "profile":
                router.go("/profile", {"name": "John"})
            case "settings":
                router.go("/settings")
            case _:
                set_appstate({"auth_user": None})
                router.go("/login")

    theme = use_context(ThemeContext)

    theme_icon = create_memo(lambda: "moon" if theme() == "dark" else "sun")

    def toggle_theme(event):
        console.log(my_ref['current'])

        if theme() == "light":
            ThemeContext.set_value("dark")
        else:
            ThemeContext.set_value("light")
    
    return t.div({"class_name": "dropdown-hoist"}, [
        t.sl_icon_button({
            "ref": my_ref,
            "name": lambda: theme_icon(), 
            "class_name": "theme-switcher",
            "@click": toggle_theme }
        ),
        
        t.sl_dropdown({"hoist": ""}, [
            t.sl_icon_button({"slot": "trigger", "name": "person-gear", "class_name": "menu-trigger"}),

            t.sl_menu({"@sl-select": on_menu_select}, [
                t.sl_menu_item({"value": "profile"}, [
                    "Profile", 
                    t.sl_icon({"name": "person-badge", "slot": "suffix"})
                ]),

                t.sl_menu_item({"value": "settings"}, [
                    "Settings", 
                    t.sl_icon({"name": "gear", "slot": "suffix"})
                ]),
                
                t.sl_divider(),

                t.sl_menu_item({"value": "logout"}, [
                    "Logout", 
                    t.sl_icon({"name": "box-arrow-right", "slot": "suffix"})
                ]),
            ])
        ])
    ])

# Dashboard layout
@page("/")
def MainLayout(children, **props):
    
    styles = load_css(css_path="dashboard.css")

    sidebar_items = [
        SidebarItem("Dashboard", "speedometer2", "/"),
        SidebarItem("Todos", "list-check", "/todos/1"),
        SidebarItem("Counter", "1-square", "/counter"),
    ]

    return t.div({}, [
            t.div({"class_name": "container"}, [
            
            t.div({"class_name": "header"}, [
                t.div({}, [
                    t.sl_button({"class_name": "menu-btn" }, [
                       t.sl_icon({"name": "list"}), 
                    ])
                ]),

                t.p({}, "Metafor UI Framework"),

                TopbarMenu(**props)
            ]),

            t.div({"class_name": "sidebar", "id": "sidebar"}, [
                For(
                    each=sidebar_items,
                    key=lambda item, _: item.route,
                    children=sidebar_item,
                )
            ]),

            # Route outlet will be children
            t.div({"class_name": "main"}, children),
            # End of children

            t.div({"class_name": "footer"}, "Business Time!"),

            t.footer({"class_name": "footer"}, [
                "visit ",
                t.a({"href": "https://github.com/google-deepmind/metafor"}, "metafor docs"),
                " to learn Metafor",
            ]),
        ])
    ], css=styles)


# Dashboard Page
@page('')
def Dashboard(**props):
    styles = """
        h2 {
            color: #323135;
        }

        .theme-dark h2 {
            color: #eee;
        }
    """

    theme = use_context(ThemeContext)
    db_api = use_context(DBContext)

    def mounted():
        print("Dashboard Page mounted!")
        run_async(
            fetch_account
        )
        # print(db_api().DB)
    
    # on_mount (executed when the component is added to the DOM)
    on_mount(mounted)

    def dispose_home():
        print("Dashboard Page disposed!")

    # on_dispose (executed when the component is removed from the DOM)
    on_dispose(dispose_home)

    user_data, set_user_data = create_signal({
        "name": "Alice",
        "profile": {
            "age": 30,
            "roles": ["user"]
        }
    }, deep=True)

    # Create an effect that will track changes
    def user_effect():
        print(f"User changed: {user_data()}")

    create_effect(user_effect)
    # These should now all trigger the effect:
   
    # These updates will now trigger the effect without changing references
    def update_person(e):
        print("Updating person...")
        def update():
            user_data()["name"] = "Bob"
            user_data()["profile"]["age"] += 1
            user_data()["profile"]["roles"].append("admin")

        batch_updates(lambda: [
            update()
        ])


    return t.div({"class_name": "home", "@click": update_person}, [
        t.div({"class_name": lambda: f"theme-{theme()}"}, [
            t.h2({}, "Dashboard Page"),
            t.p({}, "Welcome to the home page!"),

            lambda: user_data(),
        ])
        
    ], css=styles)
