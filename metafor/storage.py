
import json
import time
from typing import Any, Dict, Optional
from js import console
from metafor.utils.runtime import is_server_side

# Import Indexie components
from metafor.indexie import Indexie, Table, Collection, Strategy, IndexedDBError, StorageError, use_live_query

# --- Browser Storage Helpers ---

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
    def __init__(self, storage_target, description):
        if is_server_side:
             self._storage = MemoryStorage()
             self.description = f"{description} (Memory Fallback)"
        elif storage_target:
            self._storage = storage_target
            self.description = description
        else:
             self._storage = MemoryStorage()
             self.description = f"{description} (Memory Fallback - Target Missing)"

    def save(self, key: str, data: Any, expires: Optional[int] = None) -> None:
        if isinstance(self._storage, MemoryStorage):
             self._storage.save(key, data, expires)
             return
        try:
            value_to_store = {"data": data}
            if expires:
                value_to_store["expires"] = time.time() + expires
            self._storage.setItem(key, json.dumps(value_to_store))
        except Exception as e:
            raise StorageError(f"Error saving to {self.description}: {e}") from e

    def load(self, key: str) -> Optional[Any]:
        if isinstance(self._storage, MemoryStorage):
            return self._storage.load(key)
        try:
            value_json = self._storage.getItem(key)
            if value_json:
                value = json.loads(value_json)
                if "expires" in value and value["expires"] is not None:
                    if value["expires"] < time.time():
                        self.clear(key) 
                        return None
                return value.get("data") 
            return None
        except json.JSONDecodeError as e:
            console.warn(f"Could not decode JSON from {self.description} for key '{key}'. Clearing item.")
            self.clear(key)
            return None
        except Exception as e:
            raise StorageError(f"Error loading from {self.description}: {e}") from e

    def remove(self, key: str, attr_key: Optional[str] = None) -> None:
        if isinstance(self._storage, MemoryStorage):
             self._storage.remove(key, attr_key)
             return
        if attr_key:
            data = self.load(key)
            if isinstance(data, dict) and attr_key in data:
                del data[attr_key]
                value_json = self._storage.getItem(key)
                expires = None
                if value_json:
                    try:
                        original_value = json.loads(value_json)
                        expires = original_value.get("expires")
                    except json.JSONDecodeError:
                        pass 
                self.save(key, data, expires=(expires - time.time()) if expires else None)
        else:
            self.clear(key)

    def clear(self, key: str):
        if isinstance(self._storage, MemoryStorage):
            self._storage.clear(key)
            return
        try:
            self._storage.removeItem(key)
        except Exception as e:
            raise StorageError(f"Error clearing key '{key}' from {self.description}: {e}") from e

if is_server_side:
    _session_storage_target = None
    _local_storage_target = None
else:
    from js import sessionStorage, localStorage
    _session_storage_target = sessionStorage
    _local_storage_target = localStorage

session_storage = BrowserStorage(_session_storage_target, "session_storage")
local_storage = BrowserStorage(_local_storage_target, "local_storage")
