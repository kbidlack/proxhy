import inspect
import logging
from asyncio import StreamReader, StreamWriter

from proxhy.plugin import ProxhyPlugin


class _ProxhyLogger(logging.LoggerAdapter):
    def __init__(self, logger: logging.Logger, instance: _Proxhy) -> None:
        super().__init__(logger)
        self._instance = instance

    def process(self, msg, kwargs):
        username = getattr(self._instance, "username", None)
        func_name = None
        frame = inspect.currentframe()
        while frame:
            if (
                "logging" not in frame.f_code.co_filename
                and frame.f_code.co_filename != __file__
            ):
                func_name = frame.f_code.co_name
                break
            frame = frame.f_back

        if username and func_name:
            prefix = f"[{username}::{func_name}]"
        elif username:
            prefix = f"[{username}]"
        elif func_name:
            prefix = f"[{func_name}]"
        else:
            prefix = ""

        return f"{prefix} {msg}" if prefix else msg, kwargs


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
