from .datatypes import TextComponent


class ProxhyException(Exception):
    """Base class for proxhy exceptions"""

    pass


class CommandException(ProxhyException):
    """If a command has an error then stuff happens"""

    def __init__(self, message: str | TextComponent):
        self.message = message
