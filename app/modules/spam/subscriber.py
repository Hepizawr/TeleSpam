import asyncio
import datetime
import random
import traceback

from loguru import logger
from telethon.errors import ChannelsTooMuchError, InviteRequestSentError, UsersTooMuchError, \
    UserAlreadyParticipantError, InviteHashExpiredError, UsernameInvalidError
from telethon.tl.functions.channels import JoinChannelRequest, GetFullChannelRequest
from telethon.hints import EntityLike
from telethon.tl.functions.messages import ImportChatInviteRequest

import config
from app.modules.base import BaseModule
from app.modules.leave_groups import LeaveGroupsModule
from app.modules.utils.db_tools import set_user_group_db, delete_user_group_db
from app.modules.utils.tools import get_groups_from_file, check_participation, check_ex_participation, \
    get_entity_messages, resolve_captcha, FileHandler, get_entity, get_entity_name

from database import session as db
from database import models
from database.models import Session


class SubscriberModule(BaseModule):
    def __init__(
            self,
            groups_file: str | None,
            groups_list: str | list[str] | None,
            groups_per_session: int = 1,
            allow_multiple_sessions_per_group: bool = False,
    ):
        """
            Module responsible for handling the process of joining to groups by sessions.

            :param groups_file: Optional path to a file containing groups.
            :param groups_list: Optional list of groups or a string that represents groups.
            :param groups_per_session: Number of groups to handle per session (default 1).
            :param allow_multiple_sessions_per_group: A boolean flag indicating whether multiple sessions are allowed to join the group.
        """
        if groups_file:
            self.groups = get_groups_from_file(groups_file)
        elif groups_list:
            self.groups = [groups_list] if isinstance(groups_list, str) else groups_list
        else:
            self.groups = []

        self.groups_file = groups_file
        self.file_handler = FileHandler()
        self.groups_per_session = groups_per_session
        self.allow_multiple_sessions_per_group = allow_multiple_sessions_per_group
        self.semaphore = asyncio.Semaphore(config.MAX_THREADS)

    @staticmethod
    async def _check_last_n_messages(session: Session, group: EntityLike, message_count: int = 20) -> bool:
        """
            Checks if the specified group has a minimum number of recent messages and meets certain conditions.

            :param session: The session objects fetched from the database.
            :param group: The group identifier (username or link).
            :param message_count: Minimum amount of messages in the group.
            :return: True if matches the condition, otherwise False.
        """

        messages = await get_entity_messages(session=session, entity=group, message_count=message_count)

        if not messages:
            logger.warning(f"Group {group} has no messages")
            return False

        elif len(messages) < message_count:
            logger.warning(f"Group {group} has less than {message_count} messages")
            return False

        elif (messages[4].date + datetime.timedelta(days=60)).timestamp() < datetime.datetime.now().timestamp():
            logger.warning(f"The fifth message in the group {group} was written later 2 months ago")
            return False

        return True

    @staticmethod
    async def _check_n_participants(session: Session, group: EntityLike, participants_min_number: int = 1000):
        """
            Checks if the specified group meets the minimum number of participants required.

            :param session: The session objects fetched from the database.
            :param group: The group identifier (username or link).
            :param participants_min_number: Minimum number of participants the group.
            :return: True if matches the condition, otherwise False.
        """
        if not (client := await session.get_async_client()):
            return False

        group_entity = await client(GetFullChannelRequest(channel=group))

        participants_count = getattr(group_entity.full_chat, 'participants_count', None)

        if not participants_count:
            logger.warning(f"It is impossible to get information about the number of participants in the group ")
            return True

        elif participants_count < participants_min_number:
            logger.warning(f"Group {group} has less than {participants_min_number} participants")
            return False

        return True

    @staticmethod
    def _check_any_other_session_in_group(current_session: Session, sessions: list[Session], group: str) -> bool:
        """
            Checks if any session from the list (excluding one) is already in the group and has not left it.

            :param current_session: Current session objects fetched from the database
            :param sessions: List of session objects fetched from the database
            :param group: The group identifier (username).
            :return: True if any session (other than excluded) is still in the group, otherwise False.
        """
        group_db = db.query(models.Group).filter_by(username=group).first()

        if not group_db:
            return False

        for session in sessions:
            if session is current_session:
                continue

            session_in_group = any(sg.username == group for sg in session.groups)

            if session_in_group:
                user_group_db = db.query(models.UserGroup).filter_by(session_id=session.id,
                                                                     group_id=group_db.id).first()

                if user_group_db and not user_group_db.leaved:
                    logger.info(f"{session}: Some sessions are already a participant of the group {group}")
                    return True

        return False

    @staticmethod
    async def join_group(session: Session, group: EntityLike) -> bool:
        """
            Attempts to join a group (channel) using the provided session.

            :param session: The session objects fetched from the database.
            :param group: The group identifier (username or link).
            :return: True if the session successfully joined the group, otherwise False.
        """
        if not (client := await session.get_async_client()):
            return False

        try:
            logger.info(f"{session} is trying to join the group {group}")

            await client(JoinChannelRequest(channel=group))
            logger.success(f"{session} successfully joined the group {group}")

            set_user_group_db(session=session, group=group)
            return True

        except ChannelsTooMuchError:
            logger.error(f"{session} got ChannelsTooMuchError while trying to join the group {group}")
            return False

        except InviteRequestSentError:
            logger.success(f"{session} has successfully requested to join the {group}")
            return False

        except InviteHashExpiredError:
            logger.error(f"{session}: {group} has expired and is not valid anymore")
            return False

        except UsernameInvalidError:
            logger.error(f"{session}: Nobody is using this username {group}, or the username is unacceptable")
            return False

        except (ValueError, TypeError):
            if "+" in group:
                group_hash = group.split("+")[1]
                return await SubscriberModule._join_group_by_hash(session=session, group_hash=group_hash)
            else:
                logger.error(f"{session} can't join chat {group} for some unknown reason")
                return False

        except:
            logger.error(f"{session}: Error while joining to group {group}")
            traceback.print_exc()
            return False

    @staticmethod
    async def _join_group_by_hash(session: Session, group_hash: str) -> bool:
        """
            Attempts to join a private group (channel) by its hash, using the session provided.

            :param session: The session objects fetched from the database.
            :param group_hash: The group hash identifier (like A4LmkR23G0IGxBE71zZfo1)
            :return: True if the session successfully joined the group, otherwise False.
        """
        if not (client := await session.get_async_client()):
            return False

        try:
            await client(ImportChatInviteRequest(hash=group_hash))

            set_user_group_db(session=session,
                              group=get_entity_name(
                                  await get_entity(session=session, identifier=f"t.me/+{group_hash}")))
            logger.success(f"{session} successfully joined the private group {group_hash}")
            return True

        except ChannelsTooMuchError:
            logger.error(f"{session} got ChannelsTooMuchError while trying to join the private group {group_hash}")
            return False

        except InviteRequestSentError:
            logger.success(f"{session} has successfully requested to join the private group {group_hash}")
            return False

        except UsersTooMuchError:
            logger.error(f"{session}, maximum number of participants in the group {group_hash}")
            return False

        except UserAlreadyParticipantError:
            logger.info(f"{session} is a participant of the group {group_hash}")
            return True

    async def _split_in_threads(self, session: Session, group: EntityLike) -> None:
        """
        Handles the process of adding a session to a group and performing necessary checks.

        :param session: The session objects fetched from the database.
        :param group: The group identifier (username or ID).
        :return: None
        """
        async with self.semaphore:
            if (check_participation(session=session, group=group) or
                    check_ex_participation(session=session, group=group)):
                return

            if not await self.join_group(session=session, group=group):
                return

            group_entity = await get_entity(session=session, identifier=group)

            if (not self.allow_multiple_sessions_per_group and self._check_any_other_session_in_group(
                    current_session=session, sessions=self.sessions, group=get_entity_name(group_entity))):
                await LeaveGroupsModule.leave_group(session=session, group=group_entity)
                delete_user_group_db(session=session, group=get_entity_name(group_entity))
                return

            if (not await self._check_last_n_messages(session=session, group=group) or
                    not await self._check_n_participants(session=session, group=group)):
                await LeaveGroupsModule.leave_group(session=session, group=group_entity)
                await self.file_handler.delete_row_from_file(file=self.groups_file, row=group)
                return

            await asyncio.sleep(10)

            if not (messages := await get_entity_messages(session=session, entity=group, message_count=50)):
                await LeaveGroupsModule.leave_group(session=session, group=group_entity)
                return

            if not await resolve_captcha(session=session, group=group, messages=messages):
                await LeaveGroupsModule.leave_group(session=session, group=group_entity)
                await self.file_handler.delete_row_from_file(file=self.groups_file, row=group)
                return

    async def _get_task(self, session: Session):
        """
        Iterates through a list of groups, processing each asynchronously.

        :param session: The session object fetched from the database.
        :return: None
        """
        for group in random.sample(self.groups, k=self.groups_per_session):
            await self._split_in_threads(session, group)

            logger.info(f"{session} is sleeping... {config.FLOOD_WAIT_TIMEOUT} left")
            await asyncio.sleep(config.FLOOD_WAIT_TIMEOUT)

    async def run(self):
        if len(self.groups) < self.groups_per_session:
            logger.error(f"Not enough groups have been given to join (<{self.groups_per_session})")

        if tasks := [self._get_task(session) for session in self.sessions]:
            await asyncio.gather(*tasks)
