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
        for session in self.sessions:
            await session.get_async_client()
