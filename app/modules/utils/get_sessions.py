from loguru import logger

from database.models import Session
from database import session as db
from database import models


def get_sessions(role: str = None, username: str = None) -> list[Session] | None:
    """
    Fetches sessions based on role or username while excluding those with banned or spam block statuses.

    :param role: Role of the session to filter.
    :param username: Username of the session to filter.
    :return: List of sessions matching the criteria or None if no sessions were found.
    """
    if role:
        return _filter_sessions_by_field('role', role)
    elif username:
        return _filter_sessions_by_field('username', username)
    else:
        logger.error("No session search parameter has been entered")
        return None


def _filter_sessions_by_field(field: str, value: str) -> list[Session] | None:
    """
    Helper function to filter sessions by a given field and value while excluding banned or spam-blocked sessions.

    :param field: The field name to filter by (e.g., 'role' or 'username').
    :param value: The value to match for the given field.
    :return: List of filtered sessions or None if no sessions were found.
    """
    sessions = db.query(models.Session).filter_by(**{field: value}).filter(
        models.Session.status.notin_(["Banned", "SpamBlock"])).all()

    if not sessions:
        logger.info(f"No sessions with the given {field} '{value}' were found")
        return None

    logger.info(f"Sessions in work: {len(sessions)}")
    return sessions
