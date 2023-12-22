from asyncio import StreamReader, StreamWriter
from hashlib import sha1

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric.padding import PKCS1v15
from cryptography.hazmat.primitives.ciphers import Cipher
from cryptography.hazmat.primitives.ciphers.algorithms import AES
from cryptography.hazmat.primitives.ciphers.modes import CFB8
from cryptography.hazmat.primitives.serialization import load_der_public_key


class Stream:
    """
    Wrapper for both StreamReader and StreamWriter because
    I cannot be bothered to use them BOTH like come on man
    """

    def __init__(self, reader: StreamReader, writer: StreamWriter):
        self.reader = reader
        self.writer = writer

        self._key = None
        self.encrypted = False
        self.open = True

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
        data = await self.reader.read(n)
        return self.decryptor.update(data) if self.encrypted else data

    def write(self, data):
        return self.writer.write(
            self.encryptor.update(data) if self.encrypted else data
        )

    async def drain(self):
        return await self.writer.drain()

    def close(self):
        self.open = False
        return self.writer.close()


def pkcs1_v15_padded_rsa_encrypt(der_public_key, decrypted):
    public_key = load_der_public_key(der_public_key)
    return public_key.encrypt(decrypted, PKCS1v15())


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
