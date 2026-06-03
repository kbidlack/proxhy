import asyncio
import zlib
from asyncio import StreamReader, StreamWriter
from enum import Enum

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.decrepit.ciphers.modes import CFB8
from cryptography.hazmat.primitives.ciphers import Cipher
from cryptography.hazmat.primitives.ciphers.algorithms import AES

from petty.protocol.datatypes import Chat, Int, String, TextComponent, VarInt


class State(Enum):
    HANDSHAKING = 0
    STATUS = 1
    LOGIN = 2
    PLAY = 3


class Stream:
    """
    Wrapper for both StreamReader and StreamWriter because
    I cannot be bothered to use them BOTH like come on man
    also implements packet sending
    """

    def __init__(self, reader: StreamReader, writer: StreamWriter):
        self.reader = reader
        self.writer = writer

        self._key = b""
        self.encrypted = False
        self.compression = False
        self.compression_threshold = -1

        self.open = True
        self.paused = False
        self._pause_event = asyncio.Event()
        self._pause_event.set()  # Initially not paused

    @property
    def key(self):
        return self._key

    @key.setter
    def key(self, value):
        self.encrypted = True
        self._key = value
        self.cipher = Cipher(AES(self.key), CFB8(self.key), backend=default_backend())
        self.encryptor = self.cipher.encryptor()
        self.decryptor = self.cipher.decryptor()

    async def read(self, n=-1):
        await self._pause_event.wait()

        try:
            data = await self.reader.read(n)
        except (BrokenPipeError, ConnectionResetError):
            self.close()
            return b""

        return self.decryptor.update(data) if self.encrypted else data

    def write(self, data):
        if transport := getattr(self.writer, "transport", None):
            if transport.is_closing():
                # socket.send() raised exception can die
                return self.close()

        if self.open:
            return self.writer.write(
                self.encryptor.update(data) if self.encrypted else data
            )

    async def drain(self):
        return await self.writer.drain()

    def close(self):
        self.open = False

        if hasattr(self, "_discard_task"):
            self._discard_task.cancel()

        if hasattr(self, "_pause_event"):
            self._pause_event.set()

        return self.writer.close()

    def pause(self, discard=False):
        self.paused = True
        self._pause_event.clear()

        if hasattr(self, "_discard_task"):
            self._discard_task.cancel()

        if discard:
            self._discard_task = asyncio.create_task(self._discard_data())

    def unpause(self):
        self.paused = False

        if hasattr(self, "_discard_task"):
            self._discard_task.cancel()

        self._pause_event.set()

    async def _discard_data(self):
        try:
            while self.paused and self.open:
                try:
                    data = await asyncio.wait_for(self.reader.read(1024), timeout=0.1)
                    if not data:
                        break
                except asyncio.TimeoutError:
                    continue
                except (BrokenPipeError, ConnectionResetError):
                    self.close()
                    break
        except asyncio.CancelledError:
            pass

    def send_packet(self, id: int, *data: bytes) -> None:
        packet = VarInt.pack(id) + b"".join(data)

        if self.compression:
            if len(packet) >= self.compression_threshold:
                data_length = VarInt.pack(len(packet))
                compressed = zlib.compress(packet)
                packet = data_length + compressed
            else:
                packet = VarInt.pack(0) + packet

        self.write(VarInt.pack(len(packet)) + packet)


class ClientStream(Stream):
    def chat(self, message: str | TextComponent) -> None:
        self.send_packet(0x02, Chat.pack_msg(message))

    def set_title(
        self,
        title: TextComponent | str,
        subtitle: TextComponent | str | None = None,
        fade_in: int = 5,
        duration: int = 150,
        fade_out: int = 10,
    ):
        # set subtitle
        if subtitle is not None:
            self.send_packet(0x45, VarInt.pack(1), Chat.pack(subtitle))
        # set timings
        self.send_packet(
            0x45,
            VarInt.pack(2),
            Int.pack(fade_in),
            Int.pack(duration),
            Int.pack(fade_out),
        )
        # main title; triggers display
        self.send_packet(0x45, VarInt.pack(0), Chat.pack(title))

    def hide_title(self):
        self.send_packet(0x45, VarInt.pack(3))

    def reset_title(self):
        self.send_packet(0x45, VarInt.pack(4))

    def set_actionbar_text(self, msg: str | TextComponent):
        self.send_packet(0x02, Chat.pack(msg) + b"\x02")


class ServerStream(Stream):
    def chat(self, message: str) -> None:
        self.send_packet(0x01, String.pack(message))
