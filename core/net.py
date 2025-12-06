import asyncio
import zlib
from asyncio import StreamReader, StreamWriter
from enum import Enum

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher
from cryptography.hazmat.primitives.ciphers.algorithms import AES
from cryptography.hazmat.primitives.ciphers.modes import CFB8

from protocol.datatypes import Chat, Int, String, TextComponent, VarInt


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
        # Wait until the stream is not paused
        await self._pause_event.wait()

        try:
            data = await self.reader.read(n)
        except (BrokenPipeError, ConnectionResetError):
            self.close()
            return b""

        return self.decryptor.update(data) if self.encrypted else data

    def write(self, data):
        # check if transport is closing/closed (works with both asyncio & uvloop)
        if self.writer.transport.is_closing():
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

        # Cancel any running discard task
        if hasattr(self, "_discard_task"):
            self._discard_task.cancel()

        # Unpause to release any hanging readers
        if hasattr(self, "_pause_event"):
            self._pause_event.set()

        return self.writer.close()

    def pause(self, discard=False):
        """
        Pause the stream. Any pending read() calls will hang until unpause() is called.

        Args:
            discard: If True, incoming data will be discarded while paused.
                    If False, data will accumulate in the reader buffer.
        """
        self.paused = True
        self._pause_event.clear()

        # Start a background task to discard incoming data if requested
        if hasattr(self, "_discard_task"):
            self._discard_task.cancel()

        if discard:
            self._discard_task = asyncio.create_task(self._discard_data())

    def unpause(self):
        """
        Unpause the stream. Any hanging read() calls will resume.
        """
        self.paused = False

        # Cancel the data discarding task
        if hasattr(self, "_discard_task"):
            self._discard_task.cancel()

        self._pause_event.set()

    async def _discard_data(self):
        """
        Background task that discards incoming data while paused.
        """
        try:
            while self.paused and self.open:
                try:
                    # Read and discard data in small chunks
                    data = await asyncio.wait_for(self.reader.read(1024), timeout=0.1)
                    if not data:
                        # Connection closed
                        break
                except asyncio.TimeoutError:
                    # No data available, continue
                    continue
                except (BrokenPipeError, ConnectionResetError):
                    self.close()
                    break
        except asyncio.CancelledError:
            # Task was cancelled, normal when unpausing
            pass

    def send_packet(self, id: int, *data: bytes) -> None:
        packet = VarInt(id) + b"".join(data)
        packet_length = VarInt(len(packet))

        if self.compression:
            if len(packet) >= self.compression_threshold:
                compressed_packet = zlib.compress(packet)
                data_length = packet_length
                packet = data_length + compressed_packet
                packet_length = VarInt(len(packet))
            else:
                packet = VarInt(0) + VarInt(id) + b"".join(data)
                packet_length = VarInt(len(packet))

        self.write(packet_length + packet)


class Client(Stream):
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
        if subtitle:
            self.send_packet(0x45, VarInt(1), Chat.pack(subtitle))
        # set timings
        self.send_packet(0x45, VarInt(2), Int(fade_in), Int(duration), Int(fade_out))
        # main title; triggers display
        self.send_packet(0x45, VarInt(0), Chat.pack(title))

    def hide_title(self):
        self.send_packet(0x45, VarInt(3))

    def reset_title(self):
        self.send_packet(0x45, VarInt(4))

    def set_actionbar_text(self, msg: str | TextComponent):
        self.send_packet(0x02, Chat.pack(msg) + b"\x02")


class Server(Stream):
    def chat(self, message: str | TextComponent) -> None:
        # technically messages to the server should only be strings
        # but I'm allowing TextComponents if they're needed for whatever reason
        self.send_packet(0x01, String(message))
