from metafor.router import Route, Router
from pages.dashboard.dashboard import Dashboard
from pages.dashboard.main_layout import MainLayout
from pages.login.login import Login
from pages.todo_list import TodoList
from components.counter import Counter
from pages.profile.profile_layout import ProfileLayout
from pages.profile.profile import Profile
from pages.settings import Settings
from route_guard import is_user_logged_in

# Define routes
routes = [
    Route(MainLayout, meta={"requires_auth": True}, propagate=True, children=[
        Route(Dashboard, page_title="Home Page"),
        Route(Counter, page_title="Counter"),
        Route(TodoList, page_title="TodoList"),
        Route(ProfileLayout, children=[
            Route(Profile, page_title="Profile"),
        ]),
        Route(Settings, page_title="Settings"),
    ]),

    Route(Login, page_title="Login")
]

router = Router(routes, initial_route="/", mode=Router.HASH_MODE)

router.before_routing(is_user_logged_in)