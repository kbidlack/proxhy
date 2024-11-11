class ProxhyException(Exception):
    """Base class for proxhy exceptions"""

    pass


class CommandException(ProxhyException):
    """If a command has an error then stuff happens"""

    def __init__(self, message):
        self.message = message
