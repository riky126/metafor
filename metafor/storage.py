import json
import time
from typing import Any, Dict, Optional, Protocol, Callable, List
from pyodide.ffi import create_proxy, JsProxy, to_js, JsException
from js import console, Object, Promise
import asyncio
import inspect

from metafor.utils.runtime import is_server_side

if is_server_side:
    session_storage = None
    local_storage = None
    indexedDB = None
else:
    from js import localStorage, sessionStorage, indexedDB

class StorageError(Exception):
    """Base exception for storage-related errors."""
    pass

class JSONDecodeError(StorageError):
    """Exception raised when JSON decoding fails."""
    pass

class IndexedDBError(StorageError):
    """Exception raised for IndexedDB specific errors."""
    pass

class StorageEngine(Protocol):
    """Protocol defining the interface for storage engines."""
    def save(self, key: str, data: Any, expires: Optional[int] = None) -> None: ...
    def load(self, key: str) -> Optional[Any]: ...
    def remove(self, key: str, attr_key: Optional[str] = None) -> None: ...
    def clear(self, key: str) -> None: ...

class MemoryStorage:
    """In-memory storage engine implementation."""
    def __init__(self):
        self._storage: Dict[str, Any] = {}

    def save(self, key: str, data: Any, expires: Optional[int] = None) -> None:
        self._storage[key] = data

    def load(self, key: str) -> Optional[Any]:
        return self._storage.get(key)

    def remove(self, key: str, attr_key: Optional[str] = None) -> None:
        if attr_key:
            data = self.load(key)
            if isinstance(data, dict) and attr_key in data:
                del data[attr_key]
                self.save(key, data)
        elif key in self._storage:
             del self._storage[key]

    def clear(self, key: str) -> None:
        if key in self._storage:
            del self._storage[key]

class BrowserStorage:
    """
    Provides dictionary-like interface to browser storage objects (localStorage, sessionStorage).
    """

    def __init__(self, storage_target, description):
        """
        Initializes the BrowserStorage instance.

        Args:
            storage_target: The browser storage object (localStorage or sessionStorage).
            description (str): Description of the storage instance.
        """
        if is_server_side:
             self._storage = MemoryStorage() # Fallback to memory storage on server
             self.description = f"{description} (Memory Fallback)"
        elif storage_target:
            self._storage = storage_target
            self.description = description
        else:
             # This case should ideally not happen if is_server_side is checked first
             # but provides a safety net.
             self._storage = MemoryStorage()
             self.description = f"{description} (Memory Fallback - Target Missing)"


    def save(self, key: str, data: Any, expires: Optional[int] = None) -> None:
        """Saves data to storage, optionally with an expiration timestamp."""
        if isinstance(self._storage, MemoryStorage):
             self._storage.save(key, data, expires)
             return
        try:
            value_to_store = {"data": data}
            if expires:
                # Store expiration as Unix timestamp (seconds since epoch)
                value_to_store["expires"] = time.time() + expires
            self._storage.setItem(key, json.dumps(value_to_store))
        except Exception as e:
            raise StorageError(f"Error saving to {self.description}: {e}") from e

    def load(self, key: str) -> Optional[Any]:
        """Loads data from storage, checking for expiration if applicable."""
        if isinstance(self._storage, MemoryStorage):
            return self._storage.load(key)
        try:
            value_json = self._storage.getItem(key)
            if value_json:
                value = json.loads(value_json)
                if "expires" in value and value["expires"] is not None:
                    if value["expires"] < time.time():
                        self.clear(key) # Remove expired item
                        return None
                return value.get("data") # Use .get for safety
            return None
        except json.JSONDecodeError as e:
            # If decoding fails, it might be old data not stored by this class.
            # Optionally clear it or return None. Clearing is safer.
            console.warn(f"Could not decode JSON from {self.description} for key '{key}'. Clearing item. Error: {e}")
            self.clear(key)
            return None

        except Exception as e:
            raise StorageError(f"Error loading from {self.description}: {e}") from e


    def remove(self, key: str, attr_key: Optional[str] = None) -> None:
        """Removes an item or a specific attribute within a stored dictionary."""
        if isinstance(self._storage, MemoryStorage):
             self._storage.remove(key, attr_key)
             return

        if attr_key:
            data = self.load(key)
            if isinstance(data, dict) and attr_key in data:
                del data[attr_key]
                # Re-save the modified dictionary without the attribute
                # Need to check if it had an expiry and preserve it
                value_json = self._storage.getItem(key)
                expires = None
                if value_json:
                    try:
                        original_value = json.loads(value_json)
                        expires = original_value.get("expires")
                    except json.JSONDecodeError:
                        pass # Ignore if original couldn't be parsed
                self.save(key, data, expires=(expires - time.time()) if expires else None)
        else:
            # Remove the entire item for the key
            self.clear(key)


    def clear(self, key: str):
        """Removes an item from storage by its key."""
        if isinstance(self._storage, MemoryStorage):
            self._storage.clear(key)
            return
        try:
            self._storage.removeItem(key)
        except Exception as e:
            raise StorageError(f"Error clearing key '{key}' from {self.description}: {e}") from e

# --- IndexedDB ---
async def _js_promise_to_future(js_promise):
    """Converts a JavaScript Promise to an asyncio Future."""
    future = asyncio.Future()

    def resolve(value):
        try:
            py_value = value.to_py() if hasattr(value, 'to_py') else value
            future.set_result(py_value)
        except Exception as e:
            future.set_result(value)

    def reject(error):
        err_msg = str(error)
        if hasattr(error, 'name') and hasattr(error, 'message'):
            err_msg = f"{error.name}: {error.message}"

        future.set_exception(IndexedDBError(err_msg))

    js_promise.then(create_proxy(resolve)).catch(create_proxy(reject))
    return await future


class DatabaseSDK :
    def __init__(self, close_db_func, get_db_func):
        self._close_db = close_db_func
        self._get_db = get_db_func
        self._db_instance = None
        self.DEBUG = False # Set to True for verbose logging
        self._connect_tasks = set() # Store pending tasks created by on_connect

    def add_connect_task(self, task: asyncio.Task):
        """Adds a task to the pending set."""
        self._connect_tasks.add(task)
        # Optional: Add a callback to automatically remove when done (alternative to handler)
        # task.add_done_callback(lambda t: self._remove_connect_task(t))

    def _remove_connect_task(self, task: asyncio.Task):
        """Removes a task from the pending set."""
        self._connect_tasks.discard(task)

    def close(self):
        """Closes the database connection and cancels pending tasks."""
        # Cancel any pending tasks associated with this connection
        # Use list() to avoid modifying the set during iteration
        for task in list(self._connect_tasks):
             if task and not task.done():
                 print(f"Cancelling pending DB task on close: {task.get_name()}")
                 task.cancel()
        self._connect_tasks.clear()

        # Close the actual DB connection
        if self._db_instance:
            self._close_db() # Call the function passed during init
            self._db_instance = None
            print("Database connection closed.")

    def to_entry(self, data: Dict[str, Any]):
        """Converts a Python dictionary to a JS object suitable for IndexedDB."""
        return to_js(data, dict_converter=Object.fromEntries)

    @property
    def DB(self):
        """Gets the database instance, ensuring it's available."""
        if not self._db_instance:
             self._db_instance = self._get_db()
             if not self._db_instance:
                 raise IndexedDBError("Database connection not yet established or failed.")
        return self._db_instance

    async def _execute_transaction(self, store_name: str, mode: str, operation: Callable):
        """Helper to execute a transaction and handle errors via async/await."""
        try:
            db = self.DB
            self.DEBUG and console.log(f"[IndexedDB] Starting transaction: store='{store_name}', mode='{mode}'")
            transaction = db.transaction(store_name, mode)
            store = transaction.objectStore(store_name)

            # --- Transaction Lifecycle Logging ---
            def transaction_error_handler(event):
                error = event.target.error
                self.DEBUG and console.error(f"[IndexedDB] Transaction Error on store '{store_name}':", error.name, error.message)
            transaction.onerror = create_proxy(transaction_error_handler)

            def transaction_complete_handler(event):
                self.DEBUG and console.log(f"[IndexedDB] Transaction Completed on store '{store_name}'")
            transaction.oncomplete = create_proxy(transaction_complete_handler)
            # --- End Transaction Lifecycle Logging ---

            self.DEBUG and console.log(f"[IndexedDB] Executing operation on store '{store_name}'...")
            request = operation(store) # e.g., store.add(data)

            # Wrap the request's success/error in a JS Promise and await it
            def promise_executor(resolve, reject):
                self.DEBUG and console.log(f"[IndexedDB] Setting up promise for request on '{store_name}'...")

                def success_handler(event):
                    result = event.target.result
                    self.DEBUG and console.log(f"[IndexedDB] Request Succeeded on '{store_name}'. Result:", result)
                    resolve(result) # Resolve the JS Promise

                def error_handler(event):
                    error = event.target.error
                    console.error(f"[IndexedDB] !!! Request Failed on '{store_name}'. Error:", error.name, error.message)
                    reject(error) # Reject the JS Promise

                request.onsuccess = create_proxy(success_handler)
                request.onerror = create_proxy(error_handler)

            js_promise = Promise.new(create_proxy(promise_executor))
            # Convert JS Promise to Python Future and await its result (or exception)
            result = await _js_promise_to_future(js_promise)
            return result # Return the Python result

        except JsException as e:
            self.DEBUG and console.error(f"[IndexedDB] JavaScript exception during transaction setup: {e}")
            raise IndexedDBError(f"JavaScript error during transaction: {e}") from e
        except Exception as e:
            self.DEBUG and console.error(f"[IndexedDB] Python exception during transaction: {e}")
            # Check if it's already an IndexedDBError from _js_promise_to_future
            if isinstance(e, IndexedDBError):
                raise e
            else:
                raise IndexedDBError(f"Error during transaction on store '{store_name}': {e}") from e

    def create_store(self, store_name: str, options: Dict[str, Any], upgrade: bool = True):
        """
        Creates an object store during an upgrade transaction.
        Returns a function to add indexes to the created store.
        """
        db = self.DB # Access DB via property to ensure it's available

        if upgrade and db.objectStoreNames.contains(store_name):
            console.log(f"Deleting existing store: {store_name}")
            db.deleteObjectStore(store_name)

        store = db.createObjectStore(store_name, self.to_entry(options))
        self.DEBUG and console.log(f"Created object store: {store_name}")

        def add_index(index_name: str, key_path: str = None, options: Dict[str, Any] = None):
            """Adds an index to the store being created."""
            key_path = key_path or index_name # Default key_path to index_name
            options = options or {}
            store.createIndex(index_name, key_path, self.to_entry(options))
            self.DEBUG and console.log(f"Created index '{index_name}' on store '{store_name}'")
            # Return add_index for potential chaining, though less common now
            return add_index

        # Return the add_index function and the store itself
        return add_index, store

    # --- CRUD Methods (using async/await and _execute_transaction) ---

    async def create(self, store_name: str, data: Dict[str, Any], key: Any = None) -> Any:
        """Adds/updates a record using put (or add if key provided). Returns the key."""
        js_data = self.to_entry(data)
        if key is not None:
            # Use add() only if a specific key is provided and we want it to fail if exists
            return await self._execute_transaction(
                store_name, "readwrite", lambda store: store.add(js_data, key)
            )
        else:
            # Use put() for general create/update
            return await self._execute_transaction(
                store_name, "readwrite", lambda store: store.put(js_data)
            )

    async def read(self, store_name: str, key: Any) -> Optional[Dict[str, Any]]:
        """Retrieves a record by key. Returns dict or None."""
        # _execute_transaction now returns the Python result directly
        return await self._execute_transaction(
            store_name, "readonly", lambda store: store.get(key)
        )

    async def read_all(self, store_name: str) -> List[Dict[str, Any]]:
        """Retrieves all records. Returns list of dicts."""
        return await self._execute_transaction(
            store_name, "readonly", lambda store: store.getAll()
        )

    async def get_by_index(self, store_name: str, index_name: str, key: Any) -> Optional[Dict[str, Any]]:
        """Retrieves a record by an index key."""
        return await self._execute_transaction(
            store_name, "readonly", lambda store: store.index(index_name).get(key)
        )

    async def update(self, store_name: str, data: Dict[str, Any]) -> Any:
        """Updates/creates a record using put. Returns the key."""
        js_data = self.to_entry(data)
        return await self._execute_transaction(
            store_name, "readwrite", lambda store: store.put(js_data)
        )

    async def delete(self, store_name: str, key: Any) -> None:
        """Deletes a record by key."""
        # Delete operation returns undefined, so no need to process result
        await self._execute_transaction(
            store_name, "readwrite", lambda store: store.delete(key)
        )

# --- BrowserDB Factory Function ---
def BrowserDB(name: str, on_connected: Optional[Callable[[DatabaseSDK], None]] = None,
              on_upgrade: Optional[Callable[[DatabaseSDK], None]] = None, # Pass SDK here too
              on_error: Optional[Callable[[Any], None]] = None,
              version: int = 1) -> Optional[DatabaseSDK]:
    """
    Initializes a connection to an IndexedDB database and returns a SDK.
    """
    if is_server_side or not indexedDB:
        print("IndexedDB is not available in this environment.")
        return None

    # Use lists/holders to manage mutable state within closures
    db_holder = [None]
    sdk_instance_holder = [None]

    # --- Get SDK instance
    def get_db_instance():
        return db_holder[0]

    def close_db_internal():
        db = db_holder[0]
        if db:
            try:
                db.close()
                db_holder[0] = None
                print(f"Internal: Database '{name}' connection closed.")
            except JsException as e:
                console.error(f"Internal: Error closing database '{name}': {e}")

    # Create the SDK instance and store it in the holder
    sdk = DatabaseSDK(close_db_internal, get_db_instance)
    sdk_instance_holder[0] = sdk

    # --- Event Handlers ---
    def onupgradeneeded_proxy(event):
        db = event.target.result
        db_holder[0] = db
        current_sdk = sdk_instance_holder[0] # Get SDK from holder

        if current_sdk:
            current_sdk._db_instance = db # Update SDK's internal DB ref
   
        print(f"Upgrading database '{name}' to version {version}...")
        if on_upgrade:
            try:
                # Pass the SDK instance to on_upgrade
                on_upgrade(current_sdk if current_sdk else db) # Pass SDK
                print("Database upgrade logic executed.")
            except Exception as e:
                console.error(f"Error during on_upgrade callback for database '{name}': {e}")
                # Optionally call the main on_error handler here if upgrade fails critically
                onerror_proxy(event) # Simulate an error event
        else:
            print("No on_upgrade callback provided.")

    def onsuccess_proxy(event):
        db = event.target.result
        db_holder[0] = db
        current_sdk = sdk_instance_holder[0] 

        if current_sdk:
            current_sdk._db_instance = db

        print(f"Database '{name}' version {db.version} opened successfully.")
        
        if on_connected:
            try:
                # Always pass the SDK instance to the connected callback
                arg_to_pass = current_sdk

                if not arg_to_pass:
                    # Should not happen if SDK created first, but handle defensively
                    console.error("Critical: SDK instance is None during onsuccess!")
                    if on_error: 
                        on_error(IndexedDBError("SDK instance unavailable on connect"))
                    return

                # Check if the callback is async
                if inspect.iscoroutinefunction(on_connected):
                    # Create the task to run the async on_connect
                    connect_task = asyncio.create_task(on_connected(arg_to_pass))
                    task_name = f"DBConnectTask-{name}-{id(connect_task)}"
                    connect_task.set_name(task_name)
                    
                    # --- Store task reference in SDK
                    arg_to_pass.add_connect_task(connect_task)
                else:
                    # Call sync callback directly
                    print("Executing sync on_connected callback.")
                    on_connected(arg_to_pass)

            except Exception as e:
                console.error(f"Error during on_connected callback setup for database '{name}': {e}")
                # Call the main on_error handler
                if on_error:
                    try: on_error(e)
                    except Exception as e_inner: console.error(f"Error in on_error fallback: {e_inner}")


    def onerror_proxy(event):
        error = event.target.error if hasattr(event, 'target') else event
        err_msg = str(error)
        if hasattr(error, 'name') and hasattr(error, 'message'):
            err_msg = f"{error.name}: {error.message}"

        console.error(f"Database '{name}' connection error: {err_msg}")
        
        db_holder[0] = None
        current_sdk = sdk_instance_holder[0]

        if current_sdk:
            current_sdk._db_instance = None

        # Call the user-provided on_error callback
        if on_error:
            try:
                on_error(IndexedDBError(err_msg))
            except Exception as e:
                console.error(f"Error during user's on_error callback for database '{name}': {e}")

    try:
        print(f"Attempting to open database '{name}' version {version}...")
        request = indexedDB.open(name, version)

        # Assign proxied handlers
        request.onupgradeneeded = create_proxy(onupgradeneeded_proxy)
        request.onsuccess = create_proxy(onsuccess_proxy)
        request.onerror = create_proxy(onerror_proxy)

    except JsException as e:
        console.error(f"Failed to initiate IndexedDB open request for '{name}': {e}")
        sdk_instance_holder[0] = None
        if on_error: 
            on_error(e)
        return None
    except Exception as e:
        console.error(f"Unexpected Python error during IndexedDB setup for '{name}': {e}")
        sdk_instance_holder[0] = None
        if on_error: 
            on_error(e)
        return None

    # Return the SDK instance held in the holder
    return sdk_instance_holder[0]


# --- Exports ---
index_db = BrowserDB

_session_storage_target = None if is_server_side else sessionStorage
_local_storage_target = None if is_server_side else localStorage

session_storage = BrowserStorage(_session_storage_target, "session_storage")
local_storage = BrowserStorage(_local_storage_target, "local_storage")