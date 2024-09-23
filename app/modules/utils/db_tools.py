from loguru import logger

from database import session as db
from database import models
from database.models import Session, Group


def set_user_group_db(session: Session, group: str) -> None:
    """
        Associates a session with a group in the database.

        :param session: The session objects fetched from the database.
        :param group: The group objects fetched from the database.
        :return:
    """
    if not (group_db := get_group_db(group=group)):
        return

    if session not in group_db.sessions:
        session.groups.append(group_db)

        try:
            db.add(session)
            db.commit()

        except Exception as e:
            db.rollback()
            logger.error(f"Error while committing changes to the database: {e}")


def delete_user_group_db(session: Session, group: str) -> None:
    """
        :param session: The session objects fetched from the database.
        :param group: The group identifier (username or link).
        :return:
    """
    group_username = group.replace('https://t.me/', '').replace('t.me/', '')

    if not (group_db := db.query(models.Group).filter_by(username=group_username).first()):
        logger.info(f"Group with username {group_username} not found in database")
        return

    if not (user_group_db := db.query(models.UserGroup).filter_by(session_id=session.id, group_id=group_db.id).first()):
        logger.info(f"No association of session {session} with group {group_username} found")
        return

    try:
        db.delete(user_group_db)
        db.commit()
        logger.success(f"Association of session {session} with group {group_username} has been successfully removed")

    except Exception as e:
        db.rollback()
        logger.error(f"Error while committing changes to the database: {e}")


def set_leave_user_group_db(session: Session, group: str) -> None:
    group_username = group.replace('https://t.me/', '').replace('t.me/', '')

    if not (group_db := db.query(models.Group).filter_by(username=group_username).first()):
        logger.info(f"Group with username {group_username} not found in database")
        return

    if not (user_group_db := db.query(models.UserGroup).filter_by(session_id=session.id, group_id=group_db.id).first()):
        logger.info(f"No association of session {session} with group {group_username} found")
        return

    try:
        user_group_db.leaved = True
        db.add(user_group_db)
        db.commit()

    except Exception as e:
        db.rollback()
        logger.error(f"Error while committing changes to the database: {e}")


def get_group_db(group: str) -> Group | None:
    """
        Retrieves a Group instance from the database based on the provided username.
        If the group does not exist in the database, it creates a new Group instance and adds it.

        :param group: The group identifier (username).
        :return: An instance of the Group class fetched from the database.
    """
    group_username = group.replace('https://t.me/', '').replace('t.me/', '')

    if not (group_db := db.query(models.Group).filter_by(username=group_username).first()):
        group_db = models.Group(username=group_username)

        try:
            db.add(group_db)
            db.commit()
            return group_db

        except Exception as e:
            db.rollback()
            logger.error(f"Error while committing changes to the database: {e}")
            return None

    return group_db
