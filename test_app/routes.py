from metafor.router import Route, Router
from home import Home

# Define routes
routes = [
    Route(Home, page_title="App")
]

router = Router(routes, initial_route="/", mode=Router.HASH_MODE)