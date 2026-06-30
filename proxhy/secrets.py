from pathlib import Path

import keyring
import orjson
from cryptography.fernet import Fernet
from platformdirs import user_data_dir


def _data_dir() -> Path:
    d = Path(user_data_dir("proxhy"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def _secrets_file() -> Path:
    return _data_dir() / "secrets.enc"


def _get_or_create_key() -> bytes:
    k = keyring.get_password("proxhy", "_encryption_key")
    if k is None:
        key = Fernet.generate_key()
        keyring.set_password("proxhy", "_encryption_key", key.decode())
        return key
    return k.encode()


def _load() -> dict:
    path = _secrets_file()
    if not path.exists():
        return {}
    try:
        fernet = Fernet(_get_or_create_key())
        return orjson.loads(fernet.decrypt(path.read_bytes()))
    except Exception:
        return {}


def _save(data: dict) -> None:
    fernet = Fernet(_get_or_create_key())
    _secrets_file().write_bytes(fernet.encrypt(orjson.dumps(data)))


def get_secret(key: str) -> str | None:
    return _load().get(key)


def set_secret(key: str, value: str) -> None:
    data = _load()
    data[key] = value
    _save(data)


def delete_secret(key: str) -> None:
    data = _load()
    if key in data:
        data.pop(key)
        _save(data)
