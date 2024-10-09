import random
import traceback

from loguru import logger
import asyncio

from telethon.hints import EntityLike
from telethon.tl.custom import Message
from telethon.tl.functions.messages import ForwardMessagesRequest

from app.modules.base import BaseModule
from app.modules.leave_groups import LeaveGroupsModule
from app.modules.spam.sender import SenderModule
from app.modules.spam.subscriber import SubscriberModule
from app.modules.utils.db_tools import delete_user_group_db
from app.modules.utils.tools import get_all_dialogs, get_entity_messages, get_entity_name, get_entity
from database.models import Session


class ResponseModule(BaseModule):
    """
    Handles forwarding new messages from user chats to an operator group and responds to the sender with a predefined message.

    :param operator_group: The group where new messages will be forwarded to.
    :param response_message: The message that will be sent back to the sender after forwarding.
    :param timeout_by_request_min: Minimum delay in seconds between each request (default is 1).
    :param timeout_by_request_max: Maximum delay in seconds between each request (default is 10).
    """

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

    @staticmethod
    async def _get_new_message(session: Session) -> list[list[Message]] | list:
        """
        Retrieve new unread messages from user chats in the given session.

        :param session: The session objects fetched from the database.
        :return: A list of lists containing new unread messages per chat, or an empty list if no unread messages exist.
        """
        session_dialogs = await get_all_dialogs(session=session)

        unread_chats = [
            chat for chat in session_dialogs
            if chat.is_user and not chat.entity.bot and chat.name != "Telegram" and chat.unread_count > 0
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
        """
        Forward a list of messages to the specified recipient.

        :param session: The session objects fetched from the database.
        :param recipient: The recipient (e.g., group or user) to forward messages to.
        :param messages: The list of messages to forward.
        :return: True if the messages were successfully forwarded, otherwise False.
        """
        if not (client := await session.get_async_client()):
            return False

        message_sender = messages[0].sender
        message_ids = [message.id for message in messages]

        try:
            logger.info(
                f"{session} is trying to forwards a messages from {get_entity_name(message_sender)} to {get_entity_name(recipient)}")
            await client(ForwardMessagesRequest(from_peer=message_sender.id, id=message_ids, to_peer=recipient))
            logger.success(
                f"{session} successfully forwarded a messages from {get_entity_name(message_sender)} to ({type(recipient)}){get_entity_name(recipient)}")
            return True

        except:
            logger.error(
                f"{session} had trouble forwarding the messages from {get_entity_name(message_sender)} to ({type(recipient)}){get_entity_name(recipient)}")
            traceback.print_exc()
            return False

    @staticmethod
    async def _mark_messages_read(session: Session, messages: list[Message]):
        """
        Mark a list of messages as read.

        :param session: The session objects fetched from the database.
        :param messages: The list of messages to mark as read.
        :return:
        """
        if not (client := await session.get_async_client()):
            return False

        message_sender = messages[0].sender

        try:
            await client.send_read_acknowledge(entity=message_sender, message=messages)

        except:
            logger.error(f"{session} had trouble marking messages as read")
            traceback.print_exc()

    async def _process_messages(self, session: Session, messages: list[Message]) -> None:
        """
        Process messages from a specific session, sending them to the operator group and then responding to the sender.

        :param session: The session objects fetched from the database.
        :param messages: The list of messages to process.
        :return: None
        """
        messages_sender = messages[0].sender
        separation_message = "-" * 50

        if getattr(messages_sender, 'username', None):
            separation_message += ' @' + messages_sender.username

        if not await SubscriberModule.join_group(session=session, group=self.operator_group):
            return

        group_entity = await get_entity(session=session, identifier=self.operator_group)

        await SenderModule.send_message(session=session, recipient=group_entity, message=separation_message)

        await self.forward_messages(session=session, recipient=group_entity, messages=messages)

        await self._mark_messages_read(session=session, messages=messages)

        await SenderModule.send_message(session=session, recipient=messages_sender, message=self.response_message)

        await LeaveGroupsModule.leave_group(session=session, group=group_entity)

        delete_user_group_db(session=session, group=get_entity_name(group_entity))

    async def run(self):
        for session in self.sessions:
            if not (new_messages := await self._get_new_message(session=session)):
                logger.info(f"{session} has no new messages")
                continue

            for messages in new_messages:
                await self._process_messages(session=session, messages=messages)
                await asyncio.sleep(random.uniform(self.timeout_by_request_min, self.timeout_by_request_max))
