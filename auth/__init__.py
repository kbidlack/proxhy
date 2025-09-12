import json
import time
from pathlib import Path
from typing import Any

import jwt
import keyring
from cryptography.fernet import Fernet
from platformdirs import user_data_dir

import auth.ms as ms


async def login(email: str, password: str) -> tuple[str, str, str]:
    """Login with email/password and cache the refresh token."""
    result = await ms.login(email, password)
    access_token = result["access_token"]
    username = result["username"]
    uuid = result["uuid"]
    refresh_token = result["refresh_token"]

    # Save auth info using refresh token
    auth_data = f"{access_token} {refresh_token} {uuid}"
    safe_set("proxhy", username, auth_data)

    return access_token, username, uuid


# ---------- CROSS-PLATFORM ENCRYPTED STORAGE ----------


def _get_data_dir() -> Path:
    """Get the platform-appropriate data directory for storing encrypted tokens."""
    data_dir = Path(user_data_dir("proxhy"))
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def _get_or_create_encryption_key() -> bytes:
    """Get encryption key from keyring or create a new one."""
    key_b64 = keyring.get_password("proxhy", "_encryption_key")
    if key_b64 is None:
        # Generate new key and store in keyring
        key = Fernet.generate_key()
        keyring.set_password("proxhy", "_encryption_key", key.decode())
        return key
    return key_b64.encode()


def _encrypt_data(data: dict[str, Any]) -> bytes:
    """Encrypt auth data using Fernet."""
    key = _get_or_create_encryption_key()
    fernet = Fernet(key)
    json_data = json.dumps(data).encode()
    return fernet.encrypt(json_data)


def _decrypt_data(encrypted_data: bytes) -> dict[str, Any]:
    """Decrypt auth data using Fernet."""
    key = _get_or_create_encryption_key()
    fernet = Fernet(key)
    json_data = fernet.decrypt(encrypted_data)
    return json.loads(json_data.decode())


def safe_set(service: str, user: str, auth_data: str) -> None:
    """
    Store auth data using cross-platform encrypted file storage.
    The encryption key is stored in the system keyring (short, under any limits).
    The actual tokens are encrypted and stored in a file.
    """
    # Parse the auth_data string back into components
    parts = auth_data.split(" ")
    if len(parts) != 3:
        raise ValueError("Invalid auth_data format")

    access_token, refresh_token, uuid = parts
    data = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "uuid": uuid,
        "timestamp": time.time(),
    }

    encrypted_data = _encrypt_data(data)

    # Store in user-specific file
    data_dir = _get_data_dir()
    user_file = data_dir / f"{user}.enc"
    user_file.write_bytes(encrypted_data)


def safe_get(service: str, user: str) -> str | None:
    """
    Retrieve auth data from encrypted file storage.
    Returns the data in the original format: "access_token refresh_token uuid"
    """
    data_dir = _get_data_dir()
    user_file = data_dir / f"{user}.enc"

    if not user_file.exists():
        return None

    try:
        encrypted_data = user_file.read_bytes()
        data = _decrypt_data(encrypted_data)

        # Return in original format
        return f"{data['access_token']} {data['refresh_token']} {data['uuid']}"
    except Exception:
        # If decryption fails, treat as if no data exists
        return None


def user_exists(username: str) -> bool:
    """Check if user has stored credentials."""
    data_dir = _get_data_dir()
    user_file = data_dir / f"{username}.enc"
    return user_file.exists()


def token_needs_refresh(username: str) -> bool:
    """Check if a user's token needs refreshing (older than 23 hours)."""
    record = safe_get("proxhy", username)
    if record is None:
        return False  # No token exists, so can't refresh

    parts = record.split(" ")
    if len(parts) != 3:
        return True  # Malformed token, needs refresh

    access_token, _, _ = parts

    try:
        iat = jwt.decode(
            access_token, algorithms=["HS256"], options={"verify_signature": False}
        )["iat"]
        token_age = time.time() - float(iat)
        return token_age > 82_800  # 23 hours in seconds

    except (jwt.InvalidTokenError, KeyError, ValueError):
        # If token is malformed, it needs refreshing
        return True


# https://pypi.org/project/msmcauthaio/
# just kidding not anymore!! now we use our own auth library because we're cool
# and got chatgpt to make it for us (sunglasses emoji)
async def load_auth_info(username: str = "") -> tuple[str, str, str]:
    """Load cached auth info and refresh token if needed."""
    record = safe_get("proxhy", username)
    if record is None:
        raise RuntimeError(f"No cached credentials for user {username!r}")

    parts = record.split(" ")
    if len(parts) != 3:
        raise RuntimeError(f"Invalid cached credential format for user {username!r}")

    access_token, refresh_token, uuid = parts

    # Check if token needs refreshing and refresh if necessary
    if token_needs_refresh(username):
        access_token, refresh_token = await _refresh_and_update_tokens(
            username, refresh_token, uuid
        )

    return access_token, username, uuid


async def _refresh_and_update_tokens(
    username: str, refresh_token: str, uuid: str
) -> tuple[str, str]:
    """Helper function to refresh tokens and update storage."""
    result = await ms.login_with_refresh_token(refresh_token)
    access_token = result["access_token"]
    new_refresh_token = result["refresh_token"]

    # Update stored credentials with new tokens
    if new_refresh_token:
        auth_data = f"{access_token} {new_refresh_token} {uuid}"
        safe_set("proxhy", username, auth_data)
        return access_token, new_refresh_token
    else:
        return access_token, refresh_token


def refresh_access_token(refresh_token: str) -> str:
    """
    Refresh a Microsoft access token using the refresh token.

    This function is now implemented using the auth module's refresh functionality.
    """
    import asyncio

    async def _refresh():
        return await ms.refresh_ms_token(refresh_token)

    # Run the async function in a new event loop if needed
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # If we're already in an async context, we can't use this function
            raise RuntimeError(
                "refresh_access_token cannot be called from async context. Use auth.refresh_ms_token directly."
            )
        else:
            result = loop.run_until_complete(_refresh())
    except RuntimeError:
        # No event loop running, create a new one
        result = asyncio.run(_refresh())

    return result["access_token"]
