import io
import json

from loguru import logger
from sqlalchemy.exc import IntegrityError
from stream_sqlite import stream_sqlite
from telethon.crypto import AuthKey
from telethon.sessions import StringSession

from database import session as db
from database.models import Proxy, Session
from app.modules.base import BaseModule
from app.modules.utils.tools import get_sessions_numbers


class SetSessionsRoleModule(BaseModule):
    def __init__(
            self,
            folder: str,
            role: str
    ):
        self.folder = folder
        self.role = role

    @staticmethod
    def convert_session_into_bytes(session_path: str) -> io.BytesIO:
        with open(session_path, "rb") as file:
            sqlite_session = io.BytesIO(file.read())
            return sqlite_session

    def from_sqlite_session_file_to_string_session(self, sqlite_session_path: str) -> StringSession | None:
        """
            Make StringSession from sqlite session file and returns it

            :param sqlite_session_path: Path to session file

            :return: StringSession
        """
        sqlite_session = self.convert_session_into_bytes(sqlite_session_path)
        stream = stream_sqlite(sqlite_session, max_buffer_size=2_048_576)
        table_rows = [row for name, _, rows in stream for row in rows if name == "sessions"]
        for row in table_rows:
            if "auth_key" not in dir(row) or row.auth_key is None:
                continue
            if None in [row.dc_id, row.server_address, row.port, row.auth_key]:
                return
            string_session = StringSession()
            string_session.set_dc(row.dc_id, row.server_address, row.port)
            string_session.auth_key = AuthKey(data=row.auth_key)
            return string_session

    def insert_session_in_db(self, session_number: str) -> None:
        """
            Insert specific session into database

            :param session_number: phone number of session

            :return: None
        """
        if session_db := db.query(Session).filter_by(phone_number=session_number).first():
            self.sessions.append(session_db)
            logger.warning(f"Session {session_number} is already in db")
            return

        session_pair_path = f"{self.folder}{session_number}"
        json_file = f"{session_pair_path}.json"
        session_file = f"{session_pair_path}.session"
        with open(json_file, "r", encoding="utf8") as file:
            account = json.load(file)

        if not (session_string := self.from_sqlite_session_file_to_string_session(session_file)):
            logger.error("StringSession is None (Something wrong with .session file)")
            return
        session_string = session_string.save()

        proxy = account.get("proxy")
        proxy_type = proxy[0]
        proxy_host = proxy[1]
        proxy_port = int(proxy[2])
        proxy_username = proxy[4] if len(proxy) >= 3 else None
        proxy_password = proxy[5] if len(proxy) >= 4 else None

        if not (proxy_db := db.query(Proxy).filter_by(
                type=proxy_type,
                host=proxy_host,
                port=proxy_port,
                username=proxy_username,
                password=proxy_password
        ).first()):
            proxy_db = Proxy(
                type=proxy_type,
                host=proxy_host,
                port=proxy_port,
                username=proxy_username,
                password=proxy_password
            )

        lang_code = account.get("lang_code")
        lang_code = lang_code if lang_code else account.get("lang_pack")
        lang_code = lang_code if "android" not in lang_code else None

        new_session = Session(
            session_string=session_string, phone_number=session_number,
            user_id=account.get("id") or account.get("user_id"), username=account.get("username"),
            first_name=account.get("first_name"), last_name=account.get("last_name"),
            two_fa=account.get("twoFA") or account.get("two_fa"), sex=account.get("sex"),
            app_id=int(account.get("app_id") or account.get("api_id")),
            app_hash=account.get("app_hash") or account.get("api_hash"),
            device_model=account.get("device") or account.get("device_model"),
            system_version=account.get("sdk"), tz_offset=account.get("tz_offset"),
            app_version=account.get("app_version"), lang_code=lang_code,
            device_token=account.get("fcmToken") or account.get("DeviceToken"),
            system_lang_code=account.get("system_lang_pack") or account.get("system_lang_code"),
            register_time=account.get("register_time"), last_time_check=account.get("last_check_time"),
            role=account.get("role"), proxy=proxy_db
        )
        self.sessions.append(new_session)

        try:
            db.add(new_session)
            db.commit()
        except IntegrityError:
            db.rollback()

    def set_role(self, session: Session):
        session.role = self.role
        logger.success(f"{session} role changed successfully")

    def run(self):
        sessions_numbers = get_sessions_numbers(self.folder)
        logger.info(f"Sessions in work: {len(sessions_numbers)}")
        for session_number in sessions_numbers:
            self.insert_session_in_db(session_number)

        for session in self.sessions:
            self.set_role(session=session)
