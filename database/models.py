import traceback

from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Text, BIGINT, Boolean
from telethon.errors import AuthKeyDuplicatedError, AuthKeyUnregisteredError, UserDeactivatedError, SessionRevokedError, \
    FloodWaitError, UserDeactivatedBanError
from telethon.sessions import StringSession
from telethon.tl.functions.contacts import GetContactsRequest

from database.custom_telethon import SafeTelethon

from loguru import logger
from app.modules.utils.enums import SessionStatus, TaskStatus, CeleryTaskStatus

Base = declarative_base()


class UserGroup(Base):
    __tablename__ = "user_group"
    session_id = Column(ForeignKey("sessions.id"), primary_key=True)
    group_id = Column(ForeignKey("groups.id"), primary_key=True)
    leaved = Column(Boolean, default=False)


class Proxy(Base):
    __tablename__ = "proxies"

    id = Column(Integer, primary_key=True)
    host = Column(String(50), nullable=False)
    port = Column(Integer, nullable=False)
    username = Column(String(50))
    password = Column(String(50))
    type = Column(Integer)

    sessions = relationship("Session", back_populates="proxy")

    def to_dict(self):
        return dict(
            host=self.host, port=self.port,
            username=self.username, password=self.password,
            type=self.type)


class Session(Base):
    __tablename__ = "sessions"

    id = Column(Integer, primary_key=True)
    session_string = Column(Text, unique=True, nullable=False)
    phone_number = Column(String(50), unique=True, nullable=False)
    user_id = Column(BIGINT)
    username = Column(String(50), unique=True)
    first_name = Column(String(50))
    last_name = Column(String(50))
    two_fa = Column(String(50))
    sex = Column(Integer)
    app_id = Column(Integer, nullable=False)
    app_hash = Column(String(50), nullable=False)
    device_model = Column(String(50))
    system_version = Column(String(50))
    app_version = Column(String(50))
    system_lang_code = Column(String(20))
    lang_code = Column(String(10))
    register_time = Column(BIGINT)
    last_time_check = Column(BIGINT)
    tz_offset = Column(BIGINT)
    role = Column(String(50))
    device_token = Column(String(200))
    status = Column(String(50), nullable=False, default=SessionStatus.FREE.value)
    flood_wait_end_time = Column(BIGINT)

    proxy_id = Column(Integer, ForeignKey("proxies.id"))
    proxy = relationship("Proxy", back_populates="sessions", lazy='subquery')
    task = relationship("SessionTask", back_populates="session", uselist=False)
    groups = relationship("Group", secondary=UserGroup.__table__, uselist=True, back_populates="sessions")
    _client = None

    def __repr__(self):
        if self.username:
            representation = f"Session {self.phone_number}({self.username})"
        else:
            representation = f"Session {self.phone_number}"
        return representation

    def create_client(self) -> SafeTelethon | None:
        if not self._client:
            cl = SafeTelethon(
                StringSession(self.session_string),
                api_id=self.app_id, api_hash=self.app_hash,
                device_model=self.device_model,
                system_version=self.system_version,
                app_version=self.app_version, tz_offset=self.tz_offset,
                lang_code=self.lang_code, device_token=self.device_token,
                system_lang_code=self.system_lang_code,
                proxy=(self.proxy.type, self.proxy.host, int(self.proxy.port), True,
                       self.proxy.username, self.proxy.password) if self.proxy else None)
            cl.connect()
            self._client = cl
        return self._client

    def get_client(self) -> SafeTelethon | None:
        try:
            client = self.create_client()
            client(GetContactsRequest(0))
            return client

        except (AttributeError, UserDeactivatedError, UserDeactivatedBanError, SessionRevokedError):
            logger.error(f"{self} is banned")
            self.status = SessionStatus.BANNED.value
            self.task.status = TaskStatus.ERROR.value
            return

        except ConnectionError:
            logger.error(f"{self} can't connect to Telegram. Most likely a problem with the servers")
            return

        except AuthKeyDuplicatedError:
            logger.error(f"{self} was used under two different IP addresses simultaneously")
            return

        except:
            logger.error(f"{self} not working, for some reason")
            traceback.print_exc()
            return

    async def _create_async_client(self) -> SafeTelethon | None:
        if not self._client:
            cl = SafeTelethon(
                StringSession(self.session_string),
                api_id=self.app_id, api_hash=self.app_hash,
                device_model=self.device_model,
                system_version=self.system_version,
                app_version=self.app_version, tz_offset=self.tz_offset,
                lang_code=self.lang_code, device_token=self.device_token,
                system_lang_code=self.system_lang_code,
                proxy=(self.proxy.type, self.proxy.host, int(self.proxy.port), True,
                       self.proxy.username, self.proxy.password) if self.proxy else None)
            await cl.connect()
            self._client = cl
        return self._client

    async def get_async_client(self) -> SafeTelethon | None:
        try:
            client = await self._create_async_client()
            await client(GetContactsRequest(0))
            return client

        except (AttributeError, UserDeactivatedError, UserDeactivatedBanError, SessionRevokedError):
            logger.error(f"{self} is banned")
            self.status = SessionStatus.BANNED.value
            self.task.status = TaskStatus.ERROR.value
            return

        except ConnectionError:
            logger.error(f"{self} can't connect to Telegram. Most likely a problem with the servers")
            return

        except AuthKeyDuplicatedError:
            logger.error(f"{self} was used under two different IP addresses simultaneously")
            return

        except:
            logger.error(f"{self} not working, for some reason")
            traceback.print_exc()
            return


class SessionTask(Base):
    __tablename__ = "session_tasks"

    id = Column(Integer, primary_key=True)
    status = Column(Integer, nullable=False, default=TaskStatus.ACTIVE)

    task_id = Column(Integer, ForeignKey("tasks.id"), unique=False)
    task = relationship("Task", back_populates="session_tasks")

    session_id = Column(Integer, ForeignKey("sessions.id"), unique=False)
    session = relationship("Session", back_populates="task", uselist=False)


class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True)
    type = Column(Integer, nullable=False)
    status = Column(Integer, nullable=False, default=TaskStatus.ACTIVE)
    start_time = Column(DateTime)

    session_tasks = relationship("SessionTask", back_populates='task', uselist=True)


class Group(Base):
    __tablename__ = "groups"
    id = Column(Integer, primary_key=True)
    username = Column(String(50), unique=True)

    sessions = relationship("Session", secondary=UserGroup.__table__, back_populates="groups")


class Log(Base):
    __tablename__ = "logs"
    id = Column(Integer, primary_key=True)
    type = Column(String(50))
    text = Column(String(255))
    celery_task_id = Column(String(255))
    timestamp = Column(BIGINT)
    sent = Column(Boolean, default=False)


class CeleryTask(Base):
    __tablename__ = "celery_tasks"
    id = Column(Integer, primary_key=True)
    celery_task_id = Column(String(255))
    status = Column(Integer, nullable=False, default=CeleryTaskStatus.ACTIVE.value)


class AutoResponseMessage(Base):
    __tablename__ = "auto_response_messages"
    id = Column(Integer, primary_key=True)
    celery_task_id = Column(String(255))
    message_text = Column(Text)


class AutoResponseAnswer(Base):
    __tablename__ = "auto_response_answers"
    id = Column(Integer, primary_key=True)
    celery_task_id = Column(String(255))
    answer_text = Column(Text)


class GroupWhereBanned(Base):
    __tablename__ = "groups_where_banned"
    id = Column(Integer, primary_key=True)
    group_username = Column(String(255))


class RolesInUse(Base):
    __tablename__ = "roles_in_use"
    id = Column(Integer, primary_key=True)
    role = Column(String(255))


class JoinConfiguration(Base):
    __tablename__ = "join_configuration"
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    roles = Column(Text)
    exclude_roles = Column(Text)
    groups_file = Column(Text)
    use_all_sessions = Column(Boolean, default=True)
    groups_per_session = Column(Integer)
    timeout = Column(Integer)
    shuffle_groups_file = Column(Boolean)
