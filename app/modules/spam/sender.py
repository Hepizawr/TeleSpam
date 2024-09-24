import asyncio
import random
import traceback

from loguru import logger
from database import session as db
from telethon.errors import InputUserDeactivatedError, UserBannedInChannelError, ChatWriteForbiddenError, \
    ChatRestrictedError, ChatAdminRequiredError, ForbiddenError, PeerIdInvalidError, SlowModeWaitError

from telethon.hints import EntityLike, Entity

import config
from app.modules.base import BaseModule
from app.modules.leave_groups import LeaveGroupsModule
from app.modules.utils.tools import get_messages_from_file, get_entity_name, get_all_dialogs
from database import models
from database.models import Session


class SenderModule(BaseModule):
    def __init__(
            self,
            messages_file: str | None,
            messages_list: str | list[str] | None,
            timeout_by_request_min: int = 1,
            timeout_by_request_max: int = 10,
    ):

        if messages_file:
            self.messages = get_messages_from_file(messages_file)
        elif messages_list:
            self.messages = [messages_list] if isinstance(messages_list, str) else messages_list
        else:
            self.messages = []

        self.timeout_by_request_min = timeout_by_request_min
        self.timeout_by_request_max = timeout_by_request_max
        self.semaphore = asyncio.Semaphore(config.MAX_THREADS)

    @staticmethod
    def _check_any_session_was_in_group(sessions: list[Session], group: str) -> bool:
        """
        Checks if any session from the list was previously in the group and has left it.

        :param sessions: List of session objects fetched from the database.
        :param group: The group's identifier (username) as a string.
        :return: True if any session from the list left the group, otherwise False.
        """

        if not (group_db := db.query(models.Group).filter_by(username=group).first()):
            return False

        session_ids = [session.id for session in sessions]

        return db.query(models.UserGroup).filter(
            models.UserGroup.session_id.in_(session_ids),
            models.UserGroup.group_id == group_db.id,
            models.UserGroup.leaved == True
        ).first() is not None

    @staticmethod
    async def send_message(session: Session, recipient: EntityLike, message: str) -> bool:
        """
        Sends a message to the specified recipient using the provided session.

        :param session: The session objects fetched from the database.
        :param recipient: The recipient entity (user, group, etc.).
        :param message: The message content to be sent.
        :return: True if the message was sent successfully, otherwise False.
        """
        if not (client := await session.get_async_client()):
            return False

        try:
            logger.info(f"{session} is trying send message to {get_entity_name(entity=recipient)}")

            await client.send_message(entity=recipient, message=message)
            logger.success(f"{session} successfully sent message to {get_entity_name(entity=recipient)}")
            return True

        except (InputUserDeactivatedError, UserBannedInChannelError):
            logger.error(f"{session} is banned in group {get_entity_name(entity=recipient)}")
            return False

        except (ChatWriteForbiddenError, ChatRestrictedError, ChatAdminRequiredError):
            logger.error(f"{session} can't write to {get_entity_name(entity=recipient)}")
            return False

        except ForbiddenError:
            logger.error(f"{session} group {get_entity_name(entity=recipient)} is forbidden")
            return False

        except PeerIdInvalidError:
            logger.error(f"{session}: {get_entity_name(entity=recipient)} an invalid Peer was used.")
            return False

        except SlowModeWaitError as e:
            logger.error(
                f"{session} wait of {e.seconds} seconds is required before sending another message to {get_entity_name(entity=recipient)}")
            return True

        except:
            logger.error(f"{session}: Error while trying send message to {get_entity_name(entity=recipient)}")
            traceback.print_exc()
            return False

    async def _split_in_threads(self, session: Session, group: EntityLike, message: str) -> None:
        """
        Sends a message to the group using the session.

        :param session: The session objects fetched from the database.
        :param group: The target group to send the message to.
        :param message: The message content to be sent.
        :return: None
        """
        async with self.semaphore:
            if self._check_any_session_was_in_group(sessions=self.sessions, group=get_entity_name(entity=group)):
                for operator_username in config.OPERATORS_USERNAMES:
                    message.replace(operator_username, "").strip()

            if not await self.send_message(session=session, recipient=group, message=message):
                await LeaveGroupsModule.leave_group(session=session, group=group)
                return

    async def _get_task(self, session: Session, groups: list[Entity]):
        """
        Processes a list of groups, sending messages to each group asynchronously.

        :param session: The session objects fetched from the database.
        :param groups: List of group entities to send messages to.
        :return: None
        """
        for group in groups:
            await self._split_in_threads(session=session, group=group, message=random.choice(self.messages))

            sleep_time = random.uniform(self.timeout_by_request_min, self.timeout_by_request_max)
            logger.info(f"{session} is sleeping... {sleep_time} left")
            await asyncio.sleep(sleep_time)

    async def run(self):
        tasks = []

        for session in self.sessions:
            session_groups = [dialog for dialog in (await get_all_dialogs(session=session)) if
                              dialog.is_group and get_entity_name(entity=dialog) != 'cvg']
            tasks.append(self._get_task(session=session, groups=session_groups))

        if tasks:
            await asyncio.gather(*tasks)
