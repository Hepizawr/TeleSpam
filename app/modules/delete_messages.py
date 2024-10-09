import random
import traceback
from datetime import datetime
import asyncio

from loguru import logger
from telethon.hints import EntityLike
from telethon.requestiter import RequestIter
from telethon.tl.custom import Message

from app.modules.base import BaseModule
from app.modules.utils.tools import get_entity_name, get_all_dialogs
from database.models import Session
import config


class DeleteMessagesModule(BaseModule):
    """
    Handles the deletion of messages in specific groups for multiple user sessions.

    :param offset_date: Optional date to filter messages by, only messages after this date will be deleted.
    :param timeout_by_request_min: Minimum delay in seconds between each deletion request.
    :param timeout_by_request_max: Maximum delay in seconds between each deletion request.
    """

    def __init__(
            self,
            offset_date: str | None,
            timeout_by_request_min: int = 1,
            timeout_by_request_max: int = 5
    ):
        self.offset_date = datetime.strptime(offset_date, '%Y-%m-%d').date() if offset_date else None
        self.timeout_by_request_min = timeout_by_request_min
        self.timeout_by_request_max = timeout_by_request_max
        self.semaphore = asyncio.Semaphore(config.MAX_SESSIONS_PER_ONCE)

    async def _iter_session_messages(self, session: Session, group: EntityLike) -> RequestIter | None:
        """
        Retrieves an iterator for messages in the specified group for the given session.

        :param session: The session objects fetched from the database.
        :param group: The group entity from which to retrieve messages.
        :return: An iterator for messages if successful, otherwise None.
        """
        if not (client := await session.get_async_client()):
            return

        try:
            return client.iter_messages(entity=group, from_user='me', offset_date=self.offset_date)

        except:
            logger.error(f"{session} error while trying to retrieve messages from a group {get_entity_name(group)}")
            traceback.print_exc()
            return

    @staticmethod
    async def delete_message(session: Session, message: Message) -> bool:
        """
        Deletes the specified message from the chat.

        :param session: The session objects fetched from the database.
        :param message: The message object to be deleted.
        :return: True if the message is successfully deleted, otherwise False.
        """
        try:
            await message.delete()
            logger.success(f"{session} successfully deleted the message from {get_entity_name(message.chat)}")
            return True

        except:
            logger.error(f"{session} error while trying to delete message from {get_entity_name(message.chat)}")
            traceback.print_exc()
            return False

    async def _process_group(self, session: Session, group: EntityLike):
        """
        Iterates over the messages in the specified group and deletes each message.

        :param session: The session objects fetched from the database.
        :param group: The group entity whose messages need to be deleted.
        :return: None
        """
        async for message in await self._iter_session_messages(session=session, group=group):
            await self.delete_message(session=session, message=message)
            await asyncio.sleep(random.uniform(self.timeout_by_request_min, self.timeout_by_request_max))
        logger.success(f"{session} all messages from the group {get_entity_name(group)} have been deleted")

    async def _get_task(self, session: Session):
        """
        Retrieves and processes all valid groups for the specified session.

        :param session: The session objects fetched from the database.
        :return: None
        """
        async with self.semaphore:
            session_groups = [dialog for dialog in (await get_all_dialogs(session=session)) if
                              dialog.is_group and get_entity_name(entity=dialog) != 'cvg']

            for group in session_groups:
                await self._process_group(session=session, group=group)

    async def run(self):
        if tasks := [self._get_task(session=session) for session in self.sessions]:
            await asyncio.gather(*tasks)
