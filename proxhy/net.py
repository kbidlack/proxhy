from __future__ import annotations

import asyncio
import zlib
from asyncio import StreamReader, StreamWriter
from hashlib import sha1

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.padding import PKCS1v15
from cryptography.hazmat.primitives.ciphers import Cipher
from cryptography.hazmat.primitives.ciphers.algorithms import AES
from cryptography.hazmat.primitives.ciphers.modes import CFB8
from cryptography.hazmat.primitives.serialization import (
    load_der_private_key,
    load_der_public_key,
)

from .datatypes import Chat, String, TextComponent, VarInt


class Stream:
    """
    Wrapper for both StreamReader and StreamWriter because
    I cannot be bothered to use them BOTH like come on man
    also implements packet sending
    """

    def __init__(self, reader: StreamReader, writer: StreamWriter):
        self.reader = reader
        self.writer = writer

        self._key = None
        self.encrypted = False
        self.compression = False
        self.compression_threshold = -1

        self.open = True
        # this isn't really used but whatever
        self.paused = False

        # more minecraft specific stuff
        self.destination = 0  # 0 = client, 1 = server

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
        if self.writer.transport._conn_lost:  # AHHHH ITS FIXED !!!
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

    # more minecraft specific stuff
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

    def chat(self, message: str | TextComponent) -> None:
        if self.destination == 0:
            self.send_packet(0x02, Chat.pack_msg(message))
        else:  # self.destination == 1; server
            # technically messages to the server should only be strings
            # but I'm allowing TextComponents if they're needed for whatever reason
            self.send_packet(0x01, String(message))


def pkcs1_v15_padded_rsa_encrypt(der_public_key, decrypted):
    public_key = load_der_public_key(der_public_key)
    return public_key.encrypt(decrypted, PKCS1v15())


def pkcs1_v15_padded_rsa_decrypt(der_private_key, encrypted):
    private_key = load_der_private_key(der_private_key, password=None)
    return private_key.decrypt(encrypted, PKCS1v15())


# https://github.com/ammaraskar/pyCraft/blob/master/minecraft/networking/encryption.py#L45-L62
def generate_verification_hash(
    server_id: bytes, shared_secret: bytes, public_key: bytes
) -> str:
    verification_hash = sha1()
    verification_hash.update(server_id)
    verification_hash.update(shared_secret)
    verification_hash.update(public_key)

    number = int.from_bytes(verification_hash.digest(), byteorder="big", signed=True)
    return format(number, "x")


def generate_rsa_keypair() -> tuple[bytes, bytes]:
    # Generate private key
    private_key = rsa.generate_private_key(
        public_exponent=65537, key_size=1024, backend=default_backend()
    )

    # Generate public key
    public_key = private_key.public_key()

    # Serialize private key in ASN.1 DER format
    der_private_key = private_key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )

    # Serialize public key in ASN.1 DER format
    der_public_key = public_key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    return der_private_key, der_public_key
