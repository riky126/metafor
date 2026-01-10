
from typing import Callable, Any
from js import console
import asyncio
import inspect

def use_live_query(query_fn: Callable[[], Any]):
    """
    A hook that runs a query and keeps it updated when underlying tables change.
    Uses metafor's signal system (create_effect) to track dependencies.
    """
    from metafor.core import create_signal, create_effect, on_dispose
    
    # Initialize with empty list
    data, set_data = create_signal([])
    
    def run_query():
        try:
            # We execute query_fn synchronously to capture signal dependencies (Table._version())
            # Since Table methods now strictly track version before returning coroutine,
            # this works inside the effect.
            res = query_fn()
            
            if inspect.iscoroutine(res):
                # If it's a coroutine, we spawn a task to await it
                # The effect dependency is already tracked by the synchronous call above.
                async def _await_result():
                     try:
                         val = await res
                         set_data(val)
                     except Exception as e:
                         console.error(f"Live Query Async Error: {e}")
                
                asyncio.create_task(_await_result())
            else:
                # Synchronous result
                set_data(res)
                
        except Exception as e:
            console.error(f"Live Query Execution Error: {e}")

    # Create effect to track and rerun
    effect = create_effect(run_query)
    
    on_dispose(effect.dispose)
            
    return data
