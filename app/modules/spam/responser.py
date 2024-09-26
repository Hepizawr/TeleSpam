import traceback

from loguru import logger
import asyncio

from telethon.hints import EntityLike
from telethon.tl.custom import Message
from telethon.tl.functions.messages import ForwardMessagesRequest

import config
from app.modules.base import BaseModule
from app.modules.spam.sender import SenderModule
from app.modules.utils.tools import get_all_dialogs, get_entity_messages, get_entity_name
from database.models import Session


class ResponseModule(BaseModule):
    def __init__(
            self,
            operator_group: str,
            operator_username: str,
            response_message: str,
            timeout_by_request_min: int = 1,
            timeout_by_request_max: int = 10,
    ):
        self.operator_group = operator_group
        self.operator_username = operator_username
        self.response_message = response_message
        self.timeout_by_request_min = timeout_by_request_min
        self.timeout_by_request_max = timeout_by_request_max
        self.semaphore = asyncio.Semaphore(config.MAX_THREADS)

    @staticmethod
    async def _get_new_message(session: Session):
        session_dialogs = await get_all_dialogs(session=session)

        unread_chats = [
            chat for chat in session_dialogs
            if chat.is_user and not chat.entity.bot and chat.unread_count > 0
        ]

        if unread_chats:
            new_messages = [
                await get_entity_messages(session=session, entity=unread_chat, message_count=unread_chat.unread_count)
                for unread_chat in unread_chats
            ]

            return new_messages
        return []

    @staticmethod
    async def forward_messages(session: Session, recipient: EntityLike, messages: list[Message]) -> bool:
        if not (client := await session.get_async_client()):
            return False

        message_sender = messages[0].sender
        message_ids = [message.id for message in messages]

        try:
            await client(ForwardMessagesRequest(from_peer=message_sender.id, id=message_ids, to_peer=recipient))
            logger.info(
                f"{session} successfully forwarded a message from {get_entity_name(message_sender)} to {recipient}")
            return True

        except:
            logger.error(
                f"{session} had trouble forwarding the message from {get_entity_name(message_sender)} to {recipient}")
            traceback.print_exc()
            return False

    async def run(self):
        for session in self.sessions:
            await self._get_new_message(session=session)
