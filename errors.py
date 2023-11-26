class CommandException(Exception):
    """If a command has an error then stuff happens"""
    def __init__(self, message):
        self.message = message
