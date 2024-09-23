from loguru import logger

from app.modules.base import BaseModule
from app.modules.utils.tools import get_entity, get_all_dialogs


class TestModule(BaseModule):
    def __init__(
            self,
            username: str
    ):
        self.username = username

    async def run(self):
        session = self.sessions.pop()
        entity_ = await get_entity(session=session, identifier=self.username)
        dialogs = await get_all_dialogs(session=session)
        logger.info(entity_)
