from __future__ import annotations

import asyncio
import zlib
from asyncio import StreamReader, StreamWriter
from enum import Enum

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher
from cryptography.hazmat.primitives.ciphers.algorithms import AES
from cryptography.hazmat.primitives.ciphers.modes import CFB8

from protocol.datatypes import Chat, String, TextComponent, VarInt


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
        # this isn't really used but whatever
        self.paused = False

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
        try:
            data = await self.reader.read(n)
        except (BrokenPipeError, ConnectionResetError):
            self.close()
            return b""

        while self.paused:
            await asyncio.sleep(0.1)

        return self.decryptor.update(data) if self.encrypted else data

    def write(self, data):
        # AHHHH ITS FIXED !!!
        if self.writer.transport._conn_lost:  # type:ignore
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
        return self.writer.close()

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


class Server(Stream):
    def chat(self, message: str | TextComponent) -> None:
        # technically messages to the server should only be strings
        # but I'm allowing TextComponents if they're needed for whatever reason
        self.send_packet(0x01, String(message))
