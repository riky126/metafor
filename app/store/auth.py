# Example usage
from typing import Any, Dict

state_slice = {
    "auth_user": None
}

def auth_reducer(state: Dict[str, Any], action: Dict[str, Any]) -> Dict[str, Any]:
    match action['type']:
        case 'SET_USER':
            return {**state, "auth_user": action['payload']}
        case 'LOGOUT':
            return {**state, "auth_user": None}
        case _:
            return state