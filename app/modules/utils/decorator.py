import signal

from loguru import logger
from functools import wraps


def timeout_decorator(timeout: int):
    """
    Decorator to timeout a function after a specified number of seconds.

    :param timeout: Maximum time to execute the function in seconds.
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            logger.warning(f"The maximum time to perform the function {timeout} seconds.")

            signal.signal(signal.SIGALRM, signal.SIG_DFL)
            signal.alarm(timeout)

            try:
                result = func(*args, **kwargs)
                return result
            finally:
                logger.success(f"{func.__name__} has completed\n\n")
                signal.alarm(0)  # Disable the alarm

        return wrapper

    return decorator
