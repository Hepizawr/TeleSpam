import click
import loguru

import config
from app.modules.spam.responser import ResponseModule
from database import session as db

from app.modules.spam.sender import SenderModule
from app.modules.utils.decorator import timeout_decorator
from database import engine, models
from database.models import Base

from app.modules.leave_groups import LeaveGroupsModule
from app.modules.spam.subscriber import SubscriberModule
from app.modules.test import TestModule
from app.modules.utils.db_tools import delete_user_group_db
from app.modules.utils.get_sessions import get_sessions
from app.modules.utils.loop import Loop


@click.group()
def cli():
    pass


@click.command()
@click.option('--role', default=None)
@click.option('--session-username', default=None)
@click.option('--groups-file', default=None)
@click.option('--groups-list', default=None)
@click.option('--groups-per-session', default=1)
@click.option('--multiple-sessions-per-group/--no-multiple-sessions-per-group', default=False)
@timeout_decorator(timeout=config.TIMEOUT_SUBSCRIBER)
def join_groups(role, session_username, groups_file, groups_list, groups_per_session, multiple_sessions_per_group):
    if not (sessions := get_sessions(role=role, username=session_username)):
        return

    module = SubscriberModule(groups_file=groups_file, groups_list=groups_list, groups_per_session=groups_per_session,
                              allow_multiple_sessions_per_group=multiple_sessions_per_group)
    loop = Loop(sessions)
    loop.start_module(module)


@click.command()
@click.option('--role', default=None)
@click.option('--session-username', default=None)
@click.option('--groups-file', default=None)
@click.option('--groups-list', default=None)
@click.option('--leave-all/--leave-not-all', default=False)
def leave_groups(role, session_username, groups_file, groups_list, leave_all):
    if not (sessions := get_sessions(role=role, username=session_username)):
        return

    module = LeaveGroupsModule(groups_file=groups_file, groups_list=groups_list, leave_all=leave_all)
    loop = Loop(sessions)
    loop.start_module(module)


@click.command()
@click.option('--role', default=None)
@click.option('--session-username', default=None)
@click.option('--messages-file', default=None)
@click.option('--messages-list', default=None)
# @timeout_decorator(timeout=config.TIMEOUT_SENDER)
def send_messages(role, session_username, messages_file, messages_list):
    if not (sessions := get_sessions(role=role, username=session_username)):
        return

    module = SenderModule(messages_file=messages_file, messages_list=messages_list)
    loop = Loop(sessions)
    loop.start_module(module)


@click.command()
@click.option('--role', default=None)
@click.option('--operator-group', required=True)
@click.option('--operator-username', required=True)
@click.option('--operator-language', default="rus")
@timeout_decorator(timeout=config.TIMEOUT_RESPONSER)
def auto_respond(role, operator_group, operator_username, operator_language):
    if not (sessions := get_sessions(role=role)):
        return

    response_messages = {
        "ukr": f"Привіт)\nНапиши мені на основний акк @{operator_username}",
        "rus": f"Приветик)\nНапиши мне на основной акк @{operator_username}",
        "us": f"Hi)\nWrite to me back on my main account @{operator_username}"
    }

    module = ResponseModule(operator_group=operator_group, response_message=response_messages.get(operator_language))
    loop = Loop(sessions)
    loop.start_module(module)


@click.command()
@click.option('--session-username', required=True)
@click.option('--group', required=True)
def delete_group_db(session_username, group):
    if not (sessions := get_sessions(username=session_username)):
        return

    delete_user_group_db(session=sessions.pop(), group=group)


@click.command()
@click.option('--role', default="checker")
@click.option('--session-username', default="None")
@click.option('--entity-username', default="t.me/+Lvd_FbV7LlgyNWVi")
def test(role, session_username, entity_username):
    # if not (sessions := get_sessions(role=role, username=session_username)):
    #     return
    sessions = db.query(models.Session).all()

    module = TestModule(username=entity_username)
    loop = Loop(sessions)
    loop.start_module(module)


def add_commands(*commands):
    for command in commands:
        cli.add_command(command)


add_commands(delete_group_db, test)
add_commands(join_groups, leave_groups, send_messages, auto_respond)

if __name__ == '__main__':
    Base.metadata.create_all(bind=engine)
    cli()
