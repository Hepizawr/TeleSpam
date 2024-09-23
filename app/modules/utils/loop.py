import traceback
import asyncio

from database import session as db_session, models
from database.models import Session, Proxy, SessionTask
from app.modules.utils.enums import TaskStatus
from app.modules.base import BaseModule


class Loop:
    """
        Main loop, place where all modules should be started

        :param sessions: list of sessions that will be using in current module
        :param proxies: proxies that will be using in current module for all sessions
    """

    def __init__(self, sessions: list[Session], proxies: list[Proxy] | None = None):
        self.db = db_session
        self.sessions = sessions
        self.sessions_tasks_reset()  # deletes all previous session tasks from db

        # creating new task for every session
        for session in self.sessions:
            if session.task and session.task.status in [TaskStatus.ACTIVE.value, TaskStatus.ERROR.value]:
                raise ValueError(f"Session {session.phone_number} already used by another task")
            task = SessionTask(status=TaskStatus.ACTIVE.value)
            session.task = task
            self.db.flush()  # TODO
            self.db.add(session)

        self.proxies = proxies if proxies else []
        self.db.commit()

    def sessions_tasks_reset(self) -> None:
        """
            Deletes all previous tasks of current sessions from database

            :return: None
        """
        sessions_ids = [session.id for session in self.sessions]
        tasks = self.db.query(models.SessionTask).filter(models.SessionTask.session_id.in_(sessions_ids)).all()
        for task in tasks:
            self.db.delete(task)
        self.db.commit()

    def start_module(self, module: BaseModule) -> None | bool:
        """
            Launches module with picked sessions and proxies

            :param module: Module that we launch
            :return: None
        """
        module(self.sessions, self.proxies)
        result = None
        try:
            if asyncio.iscoroutinefunction(module.run):
                try:
                    loop = asyncio.get_event_loop()
                except:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                loop.run_until_complete(module.run())
            else:
                result = module.run()
        except KeyboardInterrupt:
            pass
        except:
            traceback.print_exc()
        module.sync_changes(self.db)
        module.stop_tasks(self.db)
        return result
