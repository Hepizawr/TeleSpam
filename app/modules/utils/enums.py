from enum import Enum


class Sex(Enum):
    MALE = 1
    FEMALE = 2


class SessionStatus(Enum):
    FREE = "Free"
    BANNED = "Banned"
    FLOOD_WAIT = "FloodWaitBlock"
    TEMP_SPAMBLOCK = "TempSpamBlock"
    SPAMBLOCK = "SpamBlock"


class TaskStatus(Enum):
    DONE = 1
    ACTIVE = 2
    ERROR = 3


class TaskType(Enum):
    SPAM = 1
    INVITE = 2
    INVITE_VIA_ADMIN = 3
    BAN_CHECK = 4
    RESTRICTION_SCHECK = 5
    USER_PARSING = 6
    CODE_RECEIVING = 7
    PROXY_RESET = 8


class CeleryTaskStatus(Enum):
    ACTIVE = 1
    DONE = 2
    ABORTED = 3
