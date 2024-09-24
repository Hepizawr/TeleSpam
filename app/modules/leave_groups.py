import asyncio
import random
import traceback

from loguru import logger

from telethon.errors import UserNotParticipantError, FloodWaitError, ChatIdInvalidError
from telethon.tl.functions.channels import LeaveChannelRequest
from telethon.tl.functions.messages import DeleteChatUserRequest
from telethon.hints import EntityLike

import config
from app.modules.base import BaseModule
from app.modules.utils.tools import get_groups_from_file, get_entity_name, get_all_dialogs
from app.modules.utils.db_tools import set_leave_user_group_db
from database.models import Session


class LeaveGroupsModule(BaseModule):
    """
    Module responsible for handling the process of leaving groups for sessions.

    :param groups_file: Optional path to a file containing group identifiers (usernames or links).
    :param groups_list: Optional list of group identifiers (usernames or links) or a single string representing a group.
    :param leave_all: Boolean flag indicating whether the session should leave all groups or only specified ones.
    :param timeout_by_request_min: Minimum timeout between requests (default is 1 second).
    :param timeout_by_request_max: Maximum timeout between requests (default is 10 seconds).
    """

    def __init__(self,
                 groups_file: str | None,
                 groups_list: str | list[str] | None,
                 leave_all: bool,
                 timeout_by_request_min: int = 1,
                 timeout_by_request_max: int = 10,
                 ):

        if groups_file:
            self.groups = get_groups_from_file(groups_file)
        elif groups_list:
            self.groups = [groups_list] if isinstance(groups_list, str) else groups_list
        else:
            self.groups = []

        self.leave_all = leave_all
        self.timeout_by_request_min = timeout_by_request_min
        self.timeout_by_request_max = timeout_by_request_max
        self.semaphore = asyncio.Semaphore(config.MAX_THREADS)

    @staticmethod
    async def leave_group(session: Session, group: EntityLike) -> bool:
        """
        Attempts to leave a group (channel) using the provided session.

        :param session: The session objects fetched from the database.
        :param group: The group identifier (username or ID).
        :return: True if the session has successfully left the group, otherwise False.
        """
        if not (client := await session.get_async_client()):
            return False

        try:
            await client(LeaveChannelRequest(channel=group))

            logger.success(f"{session}: Successfully left group {get_entity_name(entity=group)}")
            set_leave_user_group_db(session=session, group=get_entity_name(entity=group))
            return True

        except TypeError:
            return await LeaveGroupsModule._leave_private_group(session=session, group=group)

        except UserNotParticipantError:
            logger.info(f"{session}: Not a participant in group {get_entity_name(entity=group)}")
            return False

        except FloodWaitError as e:
            logger.warning(f"{session}: Flood wait error occurred. Sleeping for {e.seconds} seconds.")
            await asyncio.sleep(config.FLOOD_WAIT_TIMEOUT)
            await LeaveGroupsModule.leave_group(session, group)
            return False

        except Exception as e:
            logger.error(f"{session}: Error while leaving group {get_entity_name(entity=group)}")
            traceback.print_exc()
            return False

    @staticmethod
    async def _leave_private_group(session: Session, group: EntityLike):
        if not (client := await session.get_async_client()):
            return False

        try:
            await client(DeleteChatUserRequest(group.entity.id, 'me'))
            logger.success(f"{session}: Successfully left private group {get_entity_name(entity=group)}")
            set_leave_user_group_db(session=session, group=get_entity_name(entity=group))
            return True

        except ChatIdInvalidError:
            logger.error(f"{session}: Invalid object ID for a chat.")
            return False

        except:
            logger.error(f"{session}: Error while leaving private group {get_entity_name(entity=group)}")
            traceback.print_exc()
            return False

    async def _split_in_threads(self, session: Session, group: EntityLike) -> None:
        """
        Processes leaving a group for a session asynchronously, split into threads.

        :param session: The session object fetched from the database.
        :param group: The group identifier (username or ID).
        :return: None
        """
        async with self.semaphore:
            await self.leave_group(session, group)
            await asyncio.sleep(random.uniform(self.timeout_by_request_min, self.timeout_by_request_max))

    async def _get_task(self, session: Session, groups: list[EntityLike]) -> None:
        """
        Iterates through a list of groups, processing each asynchronously.

        :param session: The session object fetched from the database.
        :param groups: List of group identifiers (username or ID).
        :return: None
        """
        for group in groups:
            await self._split_in_threads(session, group)

    async def run(self):
        tasks = []

        for session in self.sessions:
            session_groups = [dialog for dialog in (await get_all_dialogs(session=session)) if dialog.is_group]

            if not session_groups:
                continue

            if self.leave_all:
                tasks.append(await self._get_task(session=session, groups=session_groups))
            else:
                groups_to_process = []

                for session_group in session_groups:
                    group_name = get_entity_name(entity=session_group)
                    if group_name in self.groups:
                        groups_to_process.append(session_group)

                if groups_to_process:
                    tasks.append(await self._get_task(session=session, groups=groups_to_process))

        if tasks:
            await asyncio.gather(*tasks)
