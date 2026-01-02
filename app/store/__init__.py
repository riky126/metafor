# Combine multiple reducers
from beanstack.middleware import apply_middleware, error_middleware, logger_middleware, thunk_middleware
from beanstack.beanstack_store import create_store, combine_reducers
from beanstack.storage import local_storage, FileStorage

from .counter import counter_reducer, state_slice as counter_slice
from .auth import auth_reducer, state_slice as auth_slice

root_reducer = combine_reducers({
    'auth': auth_reducer,
    'counter': counter_reducer,
})

# Create a file-based storage engine
storage = local_storage # FileStorage(directory=".store")

# Create store with middleware
create_store_with_middleware = apply_middleware(
        error_middleware,
        logger_middleware,
        thunk_middleware
        # debounce_middleware(500)  # Debounce similar actions by 500ms
    )(create_store)

# Create a store
store = create_store_with_middleware(
    root_reducer, 
    initial_state={
        'auth': auth_slice,
        'counter': counter_slice
    },
    storage_engine=storage,
    storage_key="app_store",
    persist_keys=['auth']  # Only persist auth state
)

store.enable_debug()