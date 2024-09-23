import asyncio
import traceback

from loguru import logger
from telethon.errors import InputUserDeactivatedError, UserBannedInChannelError, ChatWriteForbiddenError, \
    ChatRestrictedError, ChatAdminRequiredError, ForbiddenError

from telethon.hints import EntityLike

import config
from app.modules.base import BaseModule
from app.modules.utils.tools import get_messages_from_file, get_entity_name
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
            self.groups = get_messages_from_file(messages_file)
        elif messages_list:
            self.groups = [messages_list] if isinstance(messages_list, str) else messages_list
        else:
            self.groups = []

        self.timeout_by_request_min = timeout_by_request_min
        self.timeout_by_request_max = timeout_by_request_max
        self.semaphore = asyncio.Semaphore(config.MAX_THREADS)

    @staticmethod
    async def send_message(session: Session, recipient: EntityLike, message: str) -> bool:
        if not (client := await session.get_async_client()):
            return False

        try:
            await client.send_message(entity=recipient, message=message)
            logger.success(f"{session} successfully sent message to {recipient}")
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

        except:
            logger.error(f"{session}: Error while trying send message to group {get_entity_name(entity=recipient)}")
            traceback.print_exc()
            return False
