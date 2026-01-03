from components import TodoList, Counter
from pages.settings import Settings
from pages.dashboard import Dashboard, MainLayout
from pages.login.login import Login
from pages.profile import Profile, ProfileLayout
from metafor.router import Route, Router

# Define routes
routes = [
    Route(MainLayout, meta={"requires_auth": True}, children=[
        Route(Dashboard, page_title="Home Page"),
        Route(TodoList),
        Route(Settings),
        Route(Counter),
        Route(ProfileLayout, children=[
            Route(Profile),
        ])
    ]),
    # Route(Counter, meta={"requires_auth": True}, page_title="test"),

    Route(Login, page_title="Login")
]

router = Router(routes, initial_route="/", mode=Router.HASH_MODE)