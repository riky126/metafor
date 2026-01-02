
# Example usage
from typing import Any, Dict

state_slice = {
    "count": 0
}

def counter_reducer(state: Dict[str, Any], action: Dict[str, Any]) -> Dict[str, Any]:

    match action['type']:
        case 'INCREMENT':
            return { **state, "count": state["count"] + 1 }
        case _:
            return state