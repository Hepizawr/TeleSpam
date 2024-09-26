import asyncio
import concurrent
import multiprocessing
import signal
import sys
import threading
import time
import traceback

from loguru import logger
from functools import wraps

from database import models
from database import session as db


def start_cron_task(role: str) -> bool:
    """
    Marks a role as 'in use' by adding it to the database.

    :param role: Role to mark as in use.
    :return: True if the role was successfully marked as in use, False if the role is already marked.
    """

    if not db.query(models.RolesInUse).filter_by(role=role).first():
        db.add(models.RolesInUse(role=role))
        db.commit()
        return True  # Role was successfully marked as in use

    return False  # Role is already in use


def stop_cron_task(role: str) -> bool:
    """
    Unmarks a role as 'in use' by removing it from the database.

    :param role: Role to unmark as in use.
    :return: True if the role was successfully removed, False if the role was not found.
    """

    if record_in_db := db.query(models.RolesInUse).filter_by(role=role).first():
        db.delete(record_in_db)
        db.commit()
        return True  # Role was successfully removed

    return False  # Role was not found


def check_if_role_in_use(role: str) -> bool:
    """
    Checks if a given role is marked as 'in use'.

    :param role: Role to check.
    :return: True if the role is in use, False otherwise.
    """
    return db.query(models.RolesInUse).filter_by(role=role).first() is not None


def cron_task_decorator(func):
    """
    A decorator to ensure that a role can only be used by one task at a time. It starts a cron task
    if the role is not currently in use and stops the task after the function is completed.

    :param func: The function to be decorated.
    :return: Wrapper function.
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        role = kwargs.get('role')

        if not role:
            logger.critical('No role provided')
            return

        # Check if the role is already in use
        if check_if_role_in_use(role):
            logger.critical(f"Sessions with role {role} are already in work!")
            return

        # Mark the role as in use and run the task
        start_cron_task(role)
        logger.info(f"Role {role} has started a cron task.")

        try:
            result = func(*args, **kwargs)
            return result
        except Exception as e:
            logger.error(f"Error occurred during execution of cron task for role {role}: {e}")
            traceback.print_exc()
        finally:
            # Always unmark the role as in use after the task finishes
            stop_cron_task(role)
            logger.info(f"Role {role} has stopped its cron task.")

    return wrapper


def timeout_decorator(timeout: int):
    """
    Decorator to timeout a function after a specified number of seconds.

    :param timeout: Maximum time to execute the function in seconds.
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            logger.warning(f"The maximum time to perform the function {timeout} seconds.")
            # Set the signal handler and an alarm
            signal.signal(signal.SIGALRM, signal.SIG_DFL)
            signal.alarm(timeout)  # Set the alarm for the timeout duration

            try:
                result = func(*args, **kwargs)  # Execute the function
                return result
            finally:
                signal.alarm(0)  # Disable the alarm

        return wrapper

    return decorator
