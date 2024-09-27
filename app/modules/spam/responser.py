import random
import traceback

from loguru import logger
import asyncio

from telethon.hints import EntityLike
from telethon.tl.custom import Message
from telethon.tl.functions.messages import ForwardMessagesRequest

import config
from app.modules.base import BaseModule
from app.modules.leave_groups import LeaveGroupsModule
from app.modules.spam.sender import SenderModule
from app.modules.spam.subscriber import SubscriberModule
from app.modules.utils.tools import get_all_dialogs, get_entity_messages, get_entity_name
from database.models import Session


class ResponseModule(BaseModule):
    def __init__(
            self,
            operator_group: str,
            response_message: str,
            timeout_by_request_min: int = 1,
            timeout_by_request_max: int = 10,
    ):
        self.operator_group = operator_group
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
                await get_entity_messages(session=session, entity=unread_chat,
                                          message_count=unread_chat.unread_count + 1)
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
            logger.info(
                f"{session} is trying to forwards a messages from {get_entity_name(message_sender)} to {recipient}")
            await client(ForwardMessagesRequest(from_peer=message_sender.id, id=message_ids, to_peer=recipient))
            logger.success(
                f"{session} successfully forwarded a messages from {get_entity_name(message_sender)} to {recipient}")
            return True

        except:
            logger.error(
                f"{session} had trouble forwarding the messages from {get_entity_name(message_sender)} to {recipient}")
            traceback.print_exc()
            return False

    @staticmethod
    async def _mark_messages_read(session: Session, messages: list[Message]):
        if not (client := await session.get_async_client()):
            return False

        message_sender = messages[0].sender

        try:
            await client.send_read_acknowledge(entity=message_sender, message=messages)

        except:
            logger.error(f"{session} had trouble marking messages as read")
            traceback.print_exc()

    async def _split_in_threads(self, session: Session, messages: list[Message]):
        async with self.semaphore:
            messages_sender = messages[0].sender
            separation_message = "-" * 50

            if getattr(messages_sender, 'username', None):
                separation_message += ' @' + messages_sender.username

            if not await SubscriberModule.join_group(session=session, group=self.operator_group):
                return

            if not await SenderModule.send_message(session=session, recipient=self.operator_group,
                                                   message=separation_message):
                return

            if not await self.forward_messages(session=session, recipient=self.operator_group, messages=messages):
                return

            await LeaveGroupsModule.leave_group(session=session, group=self.operator_group)

            await self._mark_messages_read(session=session, messages=messages)

            if not await SenderModule.send_message(session=session, recipient=messages_sender,
                                                   message=self.response_message):
                return

    async def _get_task(self, session: Session, new_messages: list[list[Message]]):
        for messages in new_messages:
            await self._split_in_threads(session=session, messages=messages)
            await asyncio.sleep(random.uniform(self.timeout_by_request_min, self.timeout_by_request_max))

    async def run(self):
        tasks = []

        for session in self.sessions:
            if not (new_messages := await self._get_new_message(session=session)):
                logger.info(f"{session} has no new messages")
                continue

            tasks.append(self._get_task(session=session, new_messages=new_messages))

        if tasks:
            await asyncio.gather(*tasks)
