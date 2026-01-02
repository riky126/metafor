import asyncio
from typing import Callable, Any, Optional, Union, Tuple, Dict, List
from js import console

class AsyncTask:
    """
    A utility class for managing async tasks in Pyodide/PyScript.
    Simplifies working with async/await and callbacks in the browser environment.
    """

    @staticmethod
    def run(
            coroutine_func: Callable,
            args: Tuple = (),
            kwargs: Dict = None,
            on_success: Optional[Callable] = None,
            on_error: Optional[Callable] = None,
            on_complete: Optional[Callable] = None,
            use_create_task: bool = True
    ) -> asyncio.Task:
        """
        Run an asynchronous function with callbacks for success, error, and completion.

        Args:
            coroutine_func: The async function to run
            args: Positional arguments to pass to the function
            kwargs: Keyword arguments to pass to the function
            on_success: Callback function that receives the result when successful
            on_error: Callback function that receives the exception when failed
            on_complete: Callback function called regardless of success/failure
            use_create_task: Whether to use create_task (True) or ensure_future (False)

        Returns:
            The created asyncio.Task object
        """
        if kwargs is None:
            kwargs = {}

        async def _wrapped_coroutine():
            try:
                # Run the original coroutine with the provided args and kwargs
                result = await coroutine_func(*args, **kwargs)
                
                if isinstance(result, Exception):
                    raise result
                
                # Call success callback if provided
                if on_success is not None:
                    on_success(result)

                return result
            except Exception as e:
                # Call error callback if provided
                if on_error is not None:
                    on_error(e)
                return None # Return None to indicate an error
            finally:
                # Call complete callback if provided
                if on_complete is not None:
                    on_complete()

        # Create and schedule the task
        if use_create_task:
            task = asyncio.create_task(_wrapped_coroutine())
        else:
            task = asyncio.ensure_future(_wrapped_coroutine())
        
        return task

    @staticmethod
    def gather(
            coroutines: List[Union[asyncio.Future, asyncio.Task, Callable]],
            on_all_complete: Optional[Callable] = None,
            on_any_error: Optional[Callable] = None
    ) -> asyncio.Task:
        """
        Run multiple async tasks and handle them as a group.

        Args:
            coroutines: List of coroutines, tasks, or async functions to run
            on_all_complete: Callback for when all tasks complete successfully
            on_any_error: Callback for when any task fails

        Returns:
            A task representing the gather operation
        """
        # Process the input to ensure we have coroutines
        prepared_coroutines = []
        for item in coroutines:
            if callable(item) and not isinstance(item, (asyncio.Future, asyncio.Task)):
                # If it's a callable but not already a Future/Task, assume it's an async function
                prepared_coroutines.append(item())
            else:
                prepared_coroutines.append(item)

        async def _gather_wrapper():
            try:
                results = await asyncio.gather(*prepared_coroutines, return_exceptions=True)
                
                # Check if any task failed
                for result in results:
                    if isinstance(result, Exception):
                        if on_any_error is not None:
                            on_any_error(result)
                        return None # Return None to indicate an error
                
                if on_all_complete is not None:
                    on_all_complete(results)

                return results
            except Exception as e:
                if on_any_error is not None:
                    on_any_error(e)
                return None # Return None to indicate an error

        return asyncio.create_task(_gather_wrapper())

    @staticmethod
    def with_timeout(
            coroutine_func: Callable,
            timeout: float,
            args: Tuple = (),
            kwargs: Dict = None,
            on_success: Optional[Callable] = None,
            on_timeout: Optional[Callable] = None,
            on_error: Optional[Callable] = None,
            on_complete: Optional[Callable] = None
    ) -> asyncio.Task:
        """
        Run an async function with a timeout.

        Args:
            coroutine_func: The async function to run
            timeout: Maximum time in seconds to wait for completion
            args: Positional arguments to pass to the function
            kwargs: Keyword arguments to pass to the function
            on_success: Callback for successful completion
            on_timeout: Callback for timeout
            on_error: Callback for other errors
            on_complete: Callback called in all cases

        Returns:
            The created task
        """
        if kwargs is None:
            kwargs = {}

        async def _timeout_wrapper():
            try:
                result = await asyncio.wait_for(coroutine_func(*args, **kwargs), timeout)
                
                if isinstance(result, Exception):
                    raise result
                
                if on_success is not None:
                    on_success(result)

                return result
            except asyncio.TimeoutError:
                if on_timeout is not None:
                    on_timeout()
                return None # Return None to indicate an error
            except Exception as e:
                if on_error is not None:
                    on_error(e)
                return None # Return None to indicate an error
            finally:
                if on_complete is not None:
                    on_complete()

        return asyncio.create_task(_timeout_wrapper())

    @staticmethod
    def cancel_task(task: asyncio.Task, on_cancelled: Optional[Callable] = None) -> bool:
        """
        Cancel a running task and optionally call a callback when cancelled.

        Args:
            task: The task to cancel
            on_cancelled: Callback to call after cancellation

        Returns:
            True if task was pending and is now cancelled, False otherwise
        """
        if task.done():
            return False

        task.cancel()

        if on_cancelled is not None:
            async def _check_cancelled():
                try:
                    await task
                except asyncio.CancelledError:
                    on_cancelled()

            asyncio.create_task(_check_cancelled())

        return True

# Create a simpler alias for the run method
run_async = AsyncTask.run
gather_async = AsyncTask.gather
run_with_timeout = AsyncTask.with_timeout
cancel_async = AsyncTask.cancel_task
