import click

from app.modules.spam.subscriber import SubscriberModule
from app.modules.spam.sender import SenderModule
from app.modules.spam.responser import ResponseModule
from app.modules.delete_messages import DeleteMessagesModule
from app.modules.invite_users import InviteUsersModule
from app.modules.sessions_role import SetSessionsRoleModule
from app.modules.leave_groups import LeaveGroupsModule

from app.modules.utils.decorator import timeout_decorator
from app.modules.utils.get_sessions import get_sessions
from app.modules.utils.loop import Loop

from database import engine
from database.models import Base

import config


@click.group()
def cli():
    pass


@click.command()
@click.option('--folder', required=True)
@click.option("--role", required=True)
def set_role(folder, role) -> None:
    """
    Command changes a role of sessions from specific folder

    :param folder: The folder from which we need to take sessions
    :param role: Role that will be added to sessions

    :return: None
    """
    set_role_module = SetSessionsRoleModule(folder=folder, role=role)
    loop = Loop([])
    loop.start_module(set_role_module)


@click.command()
@click.option('--role', default=None)
@click.option('--session-username', default=None)
@click.option('--groups-file', default=None)
@click.option('--groups-list', default=None)
@click.option('--groups-per-session', default=1)
@click.option('--multiple-sessions-per-group/--no-multiple-sessions-per-group', default=False)
@timeout_decorator(timeout=config.TIMEOUT_SUBSCRIBER)
def join_groups(role, session_username, groups_file, groups_list, groups_per_session, multiple_sessions_per_group):
    """
    Join groups using specified sessions.

    :param role: Role of the session.
    :param session_username: Username of the session.
    :param groups_file: File containing group information.
    :param groups_list: List of groups to join.
    :param groups_per_session: Number of groups to join per session.
    :param multiple_sessions_per_group: Allow multiple sessions to join the same group.
    """
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
    """
   Leave groups associated with specified sessions.

   :param role: Role of the session.
   :param session_username: Username of the session.
   :param groups_file: File containing group information.
   :param groups_list: List of groups to leave.
   :param leave_all: Leave all groups or not.
   """
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
@timeout_decorator(timeout=config.TIMEOUT_SENDER)
def send_messages(role, session_username, messages_file, messages_list):
    """
    Send messages using specified sessions.

    :param role: Role of the session.
    :param session_username: Username of the session.
    :param messages_file: File containing messages to send.
    :param messages_list: List of messages to send.
    """
    if not (sessions := get_sessions(role=role, username=session_username)):
        return

    module = SenderModule(messages_file=messages_file, messages_list=messages_list)
    loop = Loop(sessions)
    loop.start_module(module)


@click.command()
@click.option('--role', default=None)
@click.option('--session-username', default=None)
@click.option('--offset-date', default=None)
def delete_messages(role, session_username, offset_date):
    """
    Delete messages associated with specified sessions.

    :param role: Role of the session.
    :param session_username: Username of the session.
    :param offset_date: Date offset to filter messages for deletion.
    """
    if not (sessions := get_sessions(role=role, username=session_username)):
        return

    module = DeleteMessagesModule(offset_date=offset_date)
    loop = Loop(sessions)
    loop.start_module(module)


@click.command()
@click.option('--role', default=None)
@click.option('--session-username', default=None)
@click.option('--operator-group', required=True)
@click.option('--operator-username', required=True)
@click.option('--operator-language', default="rus")
@timeout_decorator(timeout=config.TIMEOUT_RESPONSER)
def auto_respond(role, session_username, operator_group, operator_username, operator_language):
    """
    Automatically respond to messages using specified sessions.

    :param role: Role of the session.
    :param session_username: Username of the session.
    :param operator_group: The group to send operator responses to.
    :param operator_username: The username of the operator.
    :param operator_language: The language for the response message.
    """
    if not (sessions := get_sessions(role=role, username=session_username)):
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
@click.option('--role', default=None)
@click.option('--session-username', default=None)
@click.option('--group', required=True)
@click.option('--admin', required=True)
@click.option('--users-file', default=None)
@click.option('--users-list', default=None)
@click.option('--users-per-session', default=2)
def invite_users(role, session_username, group, admin, users_file, users_list, users_per_session):
    """
    Invite users to a group using specified sessions.

    :param role: Role of the session.
    :param session_username: Username of the session.
    :param group: The group to invite users to.
    :param admin: Username of the admin of the group.
    :param users_file: File containing user information.
    :param users_list: List of users to invite.
    :param users_per_session: Number of users to invite per session.
    """
    if not (sessions := get_sessions(role=role, username=session_username)):
        return

    module = InviteUsersModule(group=group, admin=admin, users_file=users_file, users_list=users_list,
                               users_per_session=users_per_session)
    loop = Loop(sessions)
    loop.start_module(module)


def add_commands(*commands):
    for command in commands:
        cli.add_command(command)


add_commands(set_role, join_groups, send_messages, auto_respond,
             leave_groups, delete_messages, invite_users)

if __name__ == '__main__':
    Base.metadata.create_all(bind=engine)
    cli()
