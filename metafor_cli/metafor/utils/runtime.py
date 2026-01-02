import inspect
import sys

PLATFORM_PYODIDE = "pyodide"
PLATFORM_MICROPYTHON = "micropython"
PLATFORM_CPYTHON = "cpython"


def _detect_platform():
    if sys.platform == "emscripten":
        return PLATFORM_PYODIDE
    elif sys.platform == "webassembly" and sys.implementation.name == "micropython":
        return PLATFORM_MICROPYTHON
    elif sys.implementation.name == "cpython":
        return PLATFORM_CPYTHON


platform = _detect_platform()
is_server_side = platform not in (PLATFORM_PYODIDE, PLATFORM_MICROPYTHON)

def get_parent_function(child_func):
    # Get the caller's frame (the function calling get_parent_function)
    frame = inspect.currentframe().f_back
    # Get the code object of the child function
    child_code = child_func.__code__

    # Look through the local variables in the caller's frame
    for name, value in frame.f_locals.items():
        # Check if the value is a function and matches the child function
        if inspect.isfunction(value) and value.__code__ is child_code:
            # Get the caller's caller's frame (the parent function's frame)
            parent_frame = frame.f_back
            # Get the parent function from the globals or locals of that frame
            parent_name = parent_frame.f_code.co_name
            # Access the function object from the global namespace
            parent_func = parent_frame.f_globals.get(parent_name)
            return parent_func

        else:
            return None


def get_caller_function():
    # Get the current frame (inside get_caller_function)

    current_frame = inspect.currentframe()
    # Go back one frame to the function that called get_caller_function
    caller_frame = current_frame.f_back
    # Go back one more frame to the caller of that function
    caller_of_caller_frame = caller_frame.f_back

    if caller_of_caller_frame is None:
        return None  # No caller exists (e.g., called from top level)

    # Get the caller's function name
    caller_name = caller_of_caller_frame.f_code.co_name
    # Get the caller's function object from globals (assuming it's a global function)
    caller_func = caller_of_caller_frame.f_globals.get(caller_name)
    return caller_func