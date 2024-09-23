from abc import ABC, abstractmethod

import asyncio
from loguru import logger
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from app.modules.utils.enums import TaskStatus
from database.models import Session, Proxy


class BaseModule(ABC):
    def __call__(self, sessions: list[Session], proxies: list[Proxy]):
        """
            Here user should set sessions collection that will work on module

            :param sessions: List of Session objects fetched from the database
            :param proxies: List of Proxy objects that will be used by the module

            :return: None
        """
        self.sessions = sessions
        self.sessions_queue = asyncio.Queue()
        [self.sessions_queue.put_nowait(session) for session in self.sessions]
        self.proxies = proxies

    def sync_changes(self, db: DBSession):
        """
            This method sync all changes made during module work

            :param db: SQLAlchemy session object
            :return: None
        """
        for session in self.sessions:
            try:
                db.add(session)
                db.commit()
            except IntegrityError:
                db.rollback()
                logger.error(f"{session.phone_number} :: already exists in database")

    def stop_tasks(self, db: DBSession):
        """
                Mark all tasks associated with the current sessions as "DONE" and update the database.

                :param db: SQLAlchemy session object
                :return: None
        """
        for session in self.sessions:
            if session.task:
                session.task.status = TaskStatus.DONE.value
                db.add(session)
        db.commit()

    @abstractmethod
    def run(self):
        """
            Here user should implement logic of module
            :return: Any
        """
        raise NotImplemented()
