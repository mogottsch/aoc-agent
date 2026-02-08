from enum import IntEnum, StrEnum

DAY_25 = 25
DEFAULT_TIMEOUT_SECONDS = 30.0
MAX_TIMEOUT_SECONDS = 180.0
DEFAULT_MAX_OUTPUT_LENGTH = 2000
INCORRECT_SUBMIT_LIMIT = 3


class Part(IntEnum):
    ONE = 1
    TWO = 2


class OutputMode(StrEnum):
    TOOL = "tool"
    NATIVE = "native"
    PROMPTED = "prompted"
