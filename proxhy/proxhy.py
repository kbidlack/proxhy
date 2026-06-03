import logging
from asyncio import StreamReader, StreamWriter

from proxhy.plugin import ProxhyPlugin


class _ProxhyLogger(logging.LoggerAdapter):
    def __init__(self, logger: logging.Logger, instance: "_Proxhy") -> None:
        super().__init__(logger)
        self._instance = instance

    def process(self, msg, kwargs):
        username = getattr(self._instance, "username", None)
        prefix = f"[{username}] " if username else ""
        return f"{prefix}{msg}", kwargs


class _Proxhy(ProxhyPlugin):
    def __init__(
        # proxy params
        self,
        reader: StreamReader,
        writer: StreamWriter,
        connect_host: tuple[str, int] = (
            "mc.hypixel.net",
            25565,
        ),
        autostart: bool = True,
        # custom proxhy params
        fake_connect_host: tuple[str, int] = (
            "mc.hypixel.net",
            25565,
        ),
        dev_mode: bool = False,
    ):
        super().__init__(reader, writer, connect_host, autostart)
        self.FAKE_CONNECT_HOST = fake_connect_host
        self.dev_mode = dev_mode

        self.logger = _ProxhyLogger(logging.getLogger("proxhy"), self)


Proxhy = _Proxhy
