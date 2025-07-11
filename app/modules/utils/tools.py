import asyncio
import os
import traceback

import aiofiles
from loguru import logger

from seleniumwire import webdriver
from telethon.tl.custom import Dialog
from telethon.tl.types import MessageEntityMentionName, User, Channel, Chat
from telethon.tl.functions.messages import GetBotCallbackAnswerRequest, AcceptUrlAuthRequest
from telethon.errors import BotResponseTimeoutError, MessageIdInvalidError, ChannelPrivateError, FloodWaitError, \
    UsernameInvalidError

from database import session as db
from database import models
from database.models import Session
from telethon.hints import Entity, EntityLike, TotalList


def get_rows_from_file(file: None | str) -> list | list[str]:
    """
    Reads the content of a specified text file and returns it as a list of strings.

    :param file: Path to the text file to be read.
    :return: A list of strings if the file is read successfully, or an empty list if an error occurs.
    """
    if not file:
        return []

    try:
        with open(file, "r", encoding='utf-8') as f:
            return [line.strip() for line in f if line.strip()]

    except (OSError, IOError) as e:
        logger.error(f"Error reading file {file}: {e}")
        return []


def get_messages_from_file(file: None | str) -> list | list[str]:
    """
    Reads a file and returns its contents as a list of messages, split by the '|' delimiter.

    :param file: Text file with group identifiers(username or link)
    :return: A list of messages if successful, otherwise an empty list.
    """
    if not file:
        return []

    try:
        with open(file, "r", encoding='utf-8') as f:
            return f.read().split("|")

    except (OSError, IOError) as e:
        logger.error(f"Error reading file {file}: {e}")
        return []


class FileHandler:
    def __init__(self):
        self.semaphore = asyncio.Semaphore(1)

    async def delete_row_from_file(self, file: str, row: str) -> None:
        """
        Deletes a specified row from a file asynchronously.

        :param file: The path to the file from which the row will be deleted.
        :param row: The exact content of the row to be deleted from the file.
        :return: None
        """
        async with self.semaphore:
            try:
                async with aiofiles.open(file, mode='r', encoding='utf-8') as f:
                    rows = await f.readlines()

                rows = [r for r in rows if r.strip() != row]

                async with aiofiles.open(file, mode='w', encoding='utf-8') as f:
                    await f.writelines(rows)

            except FileNotFoundError as e:
                logger.error(f"File {file} not found.")
            except PermissionError:
                logger.error(f"Permission denied: Cannot access file {file}.")
            except Exception as e:
                logger.error(f"An unexpected error occurred: {e}")


async def get_entity(session: Session, identifier: EntityLike) -> Entity | None:
    """
    Fetches the entity of the specified group (either by username or link).

    :param session: The session objects fetched from the database.
    :param identifier: The entity identifier (username, phone, ID...).
    :return: Entity if successful, otherwise None.
    """
    if not (client := await session.get_async_client()):
        return

    try:
        entity = await client.get_entity(identifier)
        return entity

    except (TypeError, ValueError, UsernameInvalidError):
        logger.error(f"{identifier} not found")
        return

    except FloodWaitError as e:
        logger.error(f"{session} A wait of {e.seconds} seconds is required")
        return

    except:
        logger.info(f"{session} had problems while getting an entity {identifier}")
        traceback.print_exc()
        return


def get_entity_name(entity: Entity) -> str:
    """
    Retrieves the name, username, or other identifying information of the specified entity.

    :param entity: The entity object, which could be of type Dialog, Channel, User, or other.
    :return: The username if available, otherwise a fallback to title, phone number, or full name.
    """
    # Handle Dialog entity type
    if isinstance(entity, Dialog):
        return getattr(entity.entity, 'username', None) or entity.entity.title

    # Handle Channel entity type
    elif isinstance(entity, (Channel, Chat)):
        return getattr(entity, 'username', None) or entity.title

    # Handle User entity type
    elif isinstance(entity, User):
        return (getattr(entity, 'username', None) or
                getattr(entity, 'phone', None) or
                f"{entity.first_name} {entity.last_name}".strip())

    return str(entity)


async def get_entity_messages(session: Session, entity: EntityLike, message_count: int) -> TotalList | None:
    """
    Fetches a specified number of messages from the given group.

    :param session: The session object fetched from the database.
    :param entity: The entity identifier (username or ID).
    :param message_count: The number of messages to retrieve.
    :return: A list of messages if successful, otherwise an empty list.
    """
    if not (client := await session.get_async_client()):
        return

    try:
        return await client.get_messages(entity, limit=message_count)
    except ChannelPrivateError:
        logger.error(f"{session}: {get_entity_name(entity)} specified is private and you lack to access it.")
        return

    except:
        logger.error(
            f"{session} error while trying to retrieve the latest messages from a group {get_entity_name(entity)}")


async def get_async_page_with_proxy(host, port, username, password, url, timeout: int = 20):
    """
    Opens a webpage using a proxy with specified credentials, waits for a specified timeout, and then quits the browser.

    :param host: The proxy server's hostname or IP address.
    :param port: The proxy server's port number.
    :param username: The username for the proxy authentication.
    :param password: The password for the proxy authentication.
    :param url: The URL of the webpage to load.
    :param timeout: Time in seconds to wait after the page is loaded before quitting the browser (default is 20 seconds).
    """
    options = {
        'proxy': {
            'https': f'https://{username}:{password}@{host}:{port}',
        }
    }
    op = webdriver.ChromeOptions()
    op.add_argument('headless')
    driver = webdriver.Chrome(seleniumwire_options=options, options=op)
    driver.get(url)
    await asyncio.sleep(timeout)
    driver.quit()


async def resolve_captcha(session: Session, group: EntityLike, messages) -> bool:
    """
    Resolves a captcha for a bot in a group chat by interacting with bot messages that mention the user.

    This function searches through provided messages for captcha-related buttons and interacts with them using
    either callback data or a URL to resolve the captcha. If the captcha involves loading a webpage, it uses the
    session's proxy credentials to load the page.

    :param session: The Telegram session used to communicate with the bot.
    :param group: The group or channel where the bot is sending captcha messages.
    :param messages: A list of messages from the bot that may contain captcha buttons.
    :return: True if the captcha is successfully resolved, False if any error occurs during resolution.
    """
    if not (client := await session.get_async_client()):
        return False

    my_id = await client.get_peer_id('me')
    for message in messages:
        if message.reply_markup and message.entities:
            for entity in message.entities:
                if isinstance(entity, MessageEntityMentionName) and str(entity.user_id) == str(my_id):
                    try:
                        data = message.reply_markup.rows[0].buttons[0].data
                        await client(GetBotCallbackAnswerRequest(
                            peer=group,
                            msg_id=message.id,
                            game=False,
                            data=data
                        ))
                    except (BotResponseTimeoutError, MessageIdInvalidError):
                        logger.warning("The bot did not answer to the callback query in time")
                        return False
                    except AttributeError:
                        try:
                            url = message.reply_markup.rows[0].buttons[0].url
                            button_id = message.reply_markup.rows[0].buttons[0].button_id
                        except AttributeError:
                            logger.warning("Can't resolve captcha")
                            return False
                        result = await client(AcceptUrlAuthRequest(
                            write_allowed=True,
                            peer=group,
                            msg_id=message.id,
                            button_id=button_id,
                            url=url
                        ))
                        host = session.proxy.host
                        port = session.proxy.port
                        username = session.proxy.username
                        password = session.proxy.password
                        await get_async_page_with_proxy(host=host, port=port, username=username,
                                                        password=password, url=result.url, timeout=15)
                    logger.success("Captcha successfully resolved")
                    return True
    return True


def check_participation(session: Session, group: str) -> bool:
    """
    Checks if the user is currently participating in the specified group.

    :param session: The session objects fetched from the database.
    :param group: The group identifier (username).
    :return: True if the user is actively participating in the group, otherwise False.
    """
    group_username = group.replace('https://t.me/', '').replace('t.me/', '')

    for session_group in session.groups:
        if session_group.username == group_username:
            group_db = db.query(models.Group).filter_by(username=group_username).first()
            user_group_db = db.query(models.UserGroup).filter_by(session_id=session.id, group_id=group_db.id).first()
            if not user_group_db.leaved:
                logger.info(f"{session} is a participant of the group")
                return True
            return False


def check_ex_participation(session: Session, group: str) -> bool:
    """
    Checks if the user has previously participated in the specified group but has left.

    :param session: The session objects fetched from the database.
    :param group: The group identifier (username).
    :return: True if the user has left the group, False if they are still part of the group.
    """
    group_username = group.replace('https://t.me/', '').replace('t.me/', '')

    for session_group in session.groups:
        if session_group.username == group_username:
            group_db = db.query(models.Group).filter_by(username=group_username).first()
            user_group_db = db.query(models.UserGroup).filter_by(session_id=session.id, group_id=group_db.id).first()
            if user_group_db.leaved:
                logger.info(f"{session} is a ex-participant of the group")
                return True
            return False


async def get_all_dialogs(session: Session) -> list | list[Entity]:
    """
    Fetches all dialog entities for the given session.

    :param session: The session object fetched from the database.
    :return: List of all session's dialog entities (groups), otherwise an empty list.
    """
    if not (client := await session.get_async_client()):
        return []

    try:
        return await client.get_dialogs()

    except:
        logger.error(f"{session}: Error while getting dialogs")
        traceback.print_exc()
        return []


def get_sessions_numbers(folder_path: str) -> list[str]:
    """
    Gets sessions numbers from specific folder with sessions

    :param folder_path: Path to a folder with sessions
    :return: List of sessions numbers
    """
    sessions_numbers = []
    for file in os.listdir(folder_path):
        if file.endswith(".session"):
            sessions_numbers.append(file.rstrip(".session"))
    return sessions_numbers
