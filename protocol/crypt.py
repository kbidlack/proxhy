from hashlib import sha1

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.padding import PKCS1v15
from cryptography.hazmat.primitives.serialization import (
    load_der_private_key,
    load_der_public_key,
)


def pkcs1_v15_padded_rsa_encrypt(der_public_key, decrypted):
    public_key = load_der_public_key(der_public_key)
    return public_key.encrypt(decrypted, PKCS1v15())  # type:ignore


def pkcs1_v15_padded_rsa_decrypt(der_private_key, encrypted):
    private_key = load_der_private_key(der_private_key, password=None)
    return private_key.decrypt(encrypted, PKCS1v15())  # type:ignore


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
