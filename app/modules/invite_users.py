import asyncio
import datetime
import random
import traceback
from types import NoneType

from loguru import logger
from telethon.errors import ChatAdminRequiredError, UserPrivacyRestrictedError, UserNotMutualContactError, \
    UsernameInvalidError, PeerFloodError, UserChannelsTooMuchError
from telethon.hints import EntityLike
from telethon.tl.functions.channels import InviteToChannelRequest
from telethon.tl.types import UserStatusLastMonth, UserStatusOffline, User

import config
from app.modules.base import BaseModule
from app.modules.leave_groups import LeaveGroupsModule
from app.modules.spam.subscriber import SubscriberModule
from app.modules.utils.db_tools import delete_user_group_db
from app.modules.utils.tools import get_rows_from_file, get_entity, get_entity_name, FileHandler
from database.models import Session


class InviteUsersModule(BaseModule):
    """
    A module for inviting users to a specified group using multiple sessions.

    This class manages the process of inviting users to a group through Telegram sessions, handling both
    file-based and list-based user sources. It also provides options for controlling the rate of invitations
    through configurable timeouts and parallel session limits using semaphores.

    :param group: The group identifier (username or ID) where users will be invited.
    :param admin: The username of the admin who will be responsible for giving permissions.
    :param users_file: The path to a file containing a list of user identifiers (optional).
    :param users_list: A list of user identifiers (optional).
    :param users_per_session: The maximum number of users to invite per session.
    :param timeout_by_request_min: The minimum timeout between invitation requests (default is 10 seconds).
    :param timeout_by_request_max: The maximum timeout between invitation requests (default is 30 seconds).
    """

    def __init__(
            self,
            group: str,
            admin: str,
            users_file: str | None,
            users_list: list[str] | None,
            users_per_session: int,
            timeout_by_request_min: int = 10,
            timeout_by_request_max: int = 30
    ):
        if users_file:
            self.users = get_rows_from_file(users_file)
        elif users_list:
            self.users = [users_list] if isinstance(users_list, str) else users_list
        else:
            self.users = []

        self.group = group
        self.admin = admin
        self.users_file = users_file
        self.users_per_session = users_per_session
        self.timeout_by_request_min = timeout_by_request_min
        self.timeout_by_request_max = timeout_by_request_max
        self.file_handler = FileHandler()
        self.semaphore = asyncio.Semaphore(config.MAX_SESSIONS_PER_ONCE)

    async def _get_admin_session(self, admin_username: str) -> Session | None:
        """
        Retrieves the session for the specified admin user by username from the available sessions list.

        If the session is found and the user has admin rights in the group (with permissions to add other admins),
        it is returned. If not found or permissions are insufficient, logs an error and returns None.

        :param admin_username: The username of the admin to retrieve the session for.
        :return: The session of the admin if found and permissions are sufficient, otherwise None.
        """
        try:
            admin_session = [self.sessions.pop(index) for index, session in enumerate(self.sessions) if
                             session.username == admin_username].pop()
        except:
            logger.error(f"{admin_username} was not found in the sessions list")
            return None

        group_entity = await get_entity(session=admin_session, identifier=self.group)

        if group_entity.admin_rights and group_entity.admin_rights.add_admins:
            return admin_session
        else:
            logger.error(f"{admin_username} doesn't have enough admin permissions ")

        return None

    @staticmethod
    async def _check_user_was_online_recently(session: Session, user: EntityLike):
        """
        Checks if the specified user was online recently (within the last month or within the last 7 days if offline).

        :param session: The session used to fetch user data.
        :param user: The user identifier (username or ID) to check.
        :return: True if the user was online recently, otherwise False.
        """
        if not (user_entity := await get_entity(session=session, identifier=user)):
            return False

        if isinstance(user_entity, User):
            user_status = user_entity.status

            if isinstance(user_status, (UserStatusLastMonth, NoneType)):
                return False
            elif isinstance(user_status, UserStatusOffline):
                return (user_status.was_online + datetime.timedelta(
                    days=7)).timestamp() > datetime.datetime.now().timestamp()

        return True

    async def _set_admin_permissions(self, session: Session, group: EntityLike) -> bool:
        """
        Grants admin permissions to the specified session for the given group.

        The method attempts to give admin rights to the session using the current admin's session.
        Logs success or failure and returns a boolean indicating the outcome.

        :param session: The session that will receive admin rights.
        :param group: The group identifier (username or ID) where the admin rights will be set.
        :return: True if the permissions were successfully set, otherwise False.
        """
        if not (client := await self.admin.get_async_client()):
            return False

        try:
            await client.edit_admin(entity=group, user=session.username, invite_users=True)
            logger.success(f"{self.admin} successfully gave admin rights to {session}")
            return True

        except:
            logger.error(f"{self.admin} while giving admin permissions to {session}, an error occurred ")
            traceback.print_exc()
            return False

    @staticmethod
    async def invite_user(session: Session, group: EntityLike, user: EntityLike) -> bool:
        """
        Invites the specified user to the provided group using the given session.

        Handles various exceptions that may occur during the invitation process, logging the results and returning
        a boolean indicating success or failure.

        :param session: The session used to invite the user to the group.
        :param group: The group identifier (username or ID) to invite the user to.
        :param user: The user identifier (username or ID) to be invited to the group.
        :return: True if the invitation was successful or a non-fatal error occurred, otherwise False.
        """
        if not (client := await session.get_async_client()):
            return False

        try:
            await client(InviteToChannelRequest(channel=group, users=[user]))
            logger.success(
                f"{session} successfully invited the user {user} to the group {get_entity_name(group)}")
            return True

        except ChatAdminRequiredError:
            logger.error(
                f"{session} to invite the user {user} to the group {get_entity_name(group)}, need admin permissions")
            return True

        except UserPrivacyRestrictedError:
            logger.error(f"{session} user's {user} privacy settings don't allow to invite him")
            return False

        except UserNotMutualContactError:
            logger.error(f"{session} user {user} is not a mutual contact")
            return True

        except (ValueError, UsernameInvalidError):
            logger.error(f"{session} No user has {user} as username")
            return False

        except PeerFloodError:
            logger.error(f"{session} too many requests")
            return True

        except UserChannelsTooMuchError:
            logger.error(f"{session} user {user} is already in too many channels/supergroups")

        except:
            logger.error(
                f"{session} while inviting a user {user} to the group {get_entity_name(group)}, an error occurred ")
            traceback.print_exc()
            return False

    async def _get_task(self, session: Session):
        """
        Main task logic for inviting users to a group in parallel sessions.

        The method first ensures that the session joins the group, then checks if the session has admin
        permissions. If permissions are granted, it iterates over a list of users, invites them to the group,
        and removes inactive users from the file. Finally, it makes the session leave the group.

        :param session: The session objects fetched from the database.
        :return: None
        """
        async with self.semaphore:
            await asyncio.sleep(random.uniform(self.timeout_by_request_min, self.timeout_by_request_max))

            if not await SubscriberModule.join_group(session=session, group=self.group):
                return

            group_entity = await get_entity(session=session, identifier=self.group)

            await asyncio.sleep(random.uniform(self.timeout_by_request_min, self.timeout_by_request_max))

            if not await self._set_admin_permissions(session=session, group=self.group):
                await LeaveGroupsModule.leave_group(session=session, group=group_entity)
                delete_user_group_db(session=session, group=get_entity_name(group_entity))
                return

            for user in random.sample(self.users, k=min(len(self.users), self.users_per_session)):
                if not await self._check_user_was_online_recently(session=session, user=user):
                    logger.error(f"{session} user {user} has not been online for a long time")
                    await self.file_handler.delete_row_from_file(file=self.users_file, row=user)
                    continue

                if not await self.invite_user(session=session, group=group_entity, user=user):
                    await self.file_handler.delete_row_from_file(file=self.users_file, row=user)

                await asyncio.sleep(random.uniform(self.timeout_by_request_min, self.timeout_by_request_max))

            await LeaveGroupsModule.leave_group(session=session, group=group_entity)
            delete_user_group_db(session=session, group=get_entity_name(group_entity))

    async def run(self):
        if not (admin := await self._get_admin_session(admin_username=self.admin)):
            return

        self.admin = admin

        await SubscriberModule.join_group(session=self.admin, group=self.group)

        if tasks := [self._get_task(session=session) for session in self.sessions]:
            await asyncio.gather(*tasks)
