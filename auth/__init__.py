"""
Minecraft Microsoft Authentication Module.

This module provides authentication for Minecraft using Microsoft accounts
via Azure AD OAuth2.

Usage:
    import auth

    # Configure your Azure client ID (required once at startup)
    auth.set_client_id("your-azure-client-id")

    # Device code flow (recommended for CLI apps)
    device = await auth.request_device_code()
    print(device["message"])  # "Go to microsoft.com/link and enter code: XXXXXX"

    # Poll for completion (blocking until user completes auth)
    result = await auth.complete_device_code_login(device["device_code"])
    # result contains: access_token, username, uuid, refresh_token

    # Later, refresh the token
    result = await auth.load_auth_info(username)
"""

import time
from pathlib import Path
from typing import Any

import jwt
import keyring
import orjson
from cryptography.fernet import Fernet
from platformdirs import user_data_dir

import auth.ms as ms
from auth.errors import AuthException, InvalidCredentials, NotPremium

# Re-export for convenience
__all__ = [
    # Configuration
    "set_client_id",
    "get_client_id",
    # Device code flow
    "request_device_code",
    "complete_device_code_login",
    # Authorization code flow
    "get_login_url",
    "get_secure_login_data",
    "complete_auth_code_login",
    # Token management
    "load_auth_info",
    "login_with_refresh_token",
    # Storage
    "user_exists",
    "token_needs_refresh",
    "safe_set",
    "safe_get",
    # Errors
    "AuthException",
    "InvalidCredentials",
    "NotPremium",
]


# ============================================================================
# Configuration
# ============================================================================


def set_client_id(client_id: str) -> None:
    """
    Set the Azure application client ID for authentication.

    This must be called once at application startup before using
    any authentication functions.

    Args:
        client_id: Your Azure application client ID
    """
    ms.set_client_id(client_id)


def get_client_id() -> str:
    """Get the configured Azure client ID."""
    return ms.get_client_id()


# ============================================================================
# Device Code Flow (Recommended for CLI)
# ============================================================================


async def request_device_code() -> ms.DeviceCodeResponse:
    """
    Start the device code authentication flow.

    Returns a device code response containing:
    - user_code: The code the user must enter
    - device_code: Internal code for polling
    - verification_uri: URL user should visit (microsoft.com/link)
    - message: Human-readable instruction message
    - expires_in: Seconds until the code expires
    - interval: Polling interval in seconds

    Example:
        device = await auth.request_device_code()
        print(device["message"])
        # User visits microsoft.com/link and enters code
        result = await auth.complete_device_code_login(device["device_code"])
    """
    client_id = ms.get_client_id()
    return await ms.request_device_code(client_id)


async def complete_device_code_login(
    device_code: str,
    interval: int = 5,
    expires_in: int = 900,
    on_pending: Any | None = None,
) -> tuple[str, str, str]:
    """
    Complete device code login and cache credentials.

    Polls Microsoft until the user completes authentication, then
    completes the full Xbox/Minecraft flow.

    Args:
        device_code: The device_code from request_device_code()
        interval: Polling interval in seconds
        expires_in: Seconds until timeout
        on_pending: Optional callback called while waiting

    Returns:
        Tuple of (access_token, username, uuid)

    Raises:
        AuthException: If authentication fails or times out
    """
    client_id = ms.get_client_id()

    # Poll for Microsoft token
    tokens = await ms.poll_device_code(
        client_id,
        device_code,
        interval=interval,
        expires_in=expires_in,
        on_pending=on_pending,
    )

    # Complete Xbox/Minecraft authentication
    result = await ms.complete_login(
        client_id,
        tokens["access_token"],
        tokens["refresh_token"],
    )

    # Cache credentials
    access_token = result["access_token"]
    username = result["username"]
    uuid = result["uuid"]
    refresh_token = result["refresh_token"]

    auth_data = f"{access_token} {refresh_token} {uuid}"
    safe_set("proxhy", username, auth_data)

    return access_token, username, uuid


# ============================================================================
# Authorization Code Flow (for web apps or with browser)
# ============================================================================


def get_login_url(redirect_uri: str) -> str:
    """
    Get a URL to redirect users to for login.

    Args:
        redirect_uri: The URI to redirect to after login

    Returns:
        Microsoft OAuth2 login URL
    """
    client_id = ms.get_client_id()
    return ms.get_login_url(client_id, redirect_uri)


def get_secure_login_data(redirect_uri: str) -> ms.SecureLoginData:
    """
    Get secure login data with PKCE protection.

    Returns a dictionary containing:
    - login_url: URL to redirect user to
    - state: CSRF protection state (verify on callback)
    - code_verifier: PKCE verifier (needed for token exchange)

    Args:
        redirect_uri: The URI to redirect to after login

    Returns:
        SecureLoginData dictionary
    """
    client_id = ms.get_client_id()
    return ms.get_secure_login_data(client_id, redirect_uri)


async def complete_auth_code_login(
    redirect_uri: str,
    auth_code: str,
    code_verifier: str | None = None,
) -> tuple[str, str, str]:
    """
    Complete login after receiving an authorization code.

    Args:
        redirect_uri: The same redirect_uri used in get_login_url
        auth_code: The authorization code from the callback URL
        code_verifier: PKCE verifier if using secure login

    Returns:
        Tuple of (access_token, username, uuid)
    """
    client_id = ms.get_client_id()

    # Exchange code for tokens
    tokens = await ms.get_authorization_token(
        client_id,
        redirect_uri,
        auth_code,
        code_verifier,
    )

    # Complete Xbox/Minecraft authentication
    result = await ms.complete_login(
        client_id,
        tokens["access_token"],
        tokens["refresh_token"],
    )

    # Cache credentials
    access_token = result["access_token"]
    username = result["username"]
    uuid = result["uuid"]
    refresh_token = result["refresh_token"]

    auth_data = f"{access_token} {refresh_token} {uuid}"
    safe_set("proxhy", username, auth_data)

    return access_token, username, uuid


# ============================================================================
# Legacy API (login function - now raises error)
# ============================================================================


async def login(email: str, password: str) -> tuple[str, str, str]:
    """
    Legacy login function - NOT SUPPORTED.

    Microsoft no longer supports password-based authentication.
    Use device code flow instead:

        device = await auth.request_device_code()
        print(device["message"])
        result = await auth.complete_device_code_login(device["device_code"])

    Raises:
        AuthException: Always - password login is deprecated
    """
    raise AuthException(
        "Password-based login is no longer supported by Microsoft. "
        "Use auth.request_device_code() and auth.complete_device_code_login() instead.",
        code="PASSWORD-LOGIN-DEPRECATED",
    )


# ============================================================================
# Cross-Platform Encrypted Storage
# ============================================================================


def _get_data_dir() -> Path:
    """Get the platform-appropriate data directory for storing encrypted tokens."""
    data_dir = Path(user_data_dir("proxhy"))
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def _get_or_create_encryption_key() -> bytes:
    """Get encryption key from keyring or create a new one."""
    key_b64 = keyring.get_password("proxhy", "_encryption_key")
    if key_b64 is None:
        key = Fernet.generate_key()
        keyring.set_password("proxhy", "_encryption_key", key.decode())
        return key
    return key_b64.encode()


def _encrypt_data(data: dict[str, Any]) -> bytes:
    """Encrypt auth data using Fernet."""
    key = _get_or_create_encryption_key()
    fernet = Fernet(key)
    return fernet.encrypt(orjson.dumps(data))


def _decrypt_data(encrypted_data: bytes) -> dict[str, Any]:
    """Decrypt auth data using Fernet."""
    key = _get_or_create_encryption_key()
    fernet = Fernet(key)
    return orjson.loads(fernet.decrypt(encrypted_data))


def safe_set(service: str, user: str, auth_data: str) -> None:
    """
    Store auth data using cross-platform encrypted file storage.

    The encryption key is stored in the system keyring (short, under any limits).
    The actual tokens are encrypted and stored in a file.
    """
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

    data_dir = _get_data_dir()
    user_file = data_dir / f"{user}.enc"
    user_file.write_bytes(encrypted_data)


def safe_get(service: str, user: str) -> str | None:
    """
    Retrieve auth data from encrypted file storage.

    Returns the data in the format: "access_token refresh_token uuid"
    """
    data_dir = _get_data_dir()
    user_file = data_dir / f"{user}.enc"

    if not user_file.exists():
        return None

    try:
        encrypted_data = user_file.read_bytes()
        data = _decrypt_data(encrypted_data)
        return f"{data['access_token']} {data['refresh_token']} {data['uuid']}"
    except Exception:
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
        return False

    parts = record.split(" ")
    if len(parts) != 3:
        return True

    access_token = parts[0]

    try:
        decoded = jwt.decode(
            access_token,
            algorithms=["HS256"],
            options={"verify_signature": False},
        )
        iat = decoded.get("iat")
        if iat is None:
            return True
        token_age = time.time() - float(iat)
        return token_age > 82_800  # 23 hours

    except (jwt.InvalidTokenError, KeyError, ValueError):
        return True


async def load_auth_info(username: str = "") -> tuple[str, str, str]:
    """
    Load cached auth info and refresh token if needed.

    Args:
        username: The Minecraft username to load credentials for

    Returns:
        Tuple of (access_token, username, uuid)

    Raises:
        RuntimeError: If no cached credentials exist
    """
    record = safe_get("proxhy", username)
    if record is None:
        raise RuntimeError(f"No cached credentials for user {username!r}")

    parts = record.split(" ")
    if len(parts) != 3:
        raise RuntimeError(f"Invalid cached credential format for user {username!r}")

    access_token, refresh_token, uuid = parts

    if token_needs_refresh(username):
        access_token, refresh_token = await _refresh_and_update_tokens(
            username, refresh_token, uuid
        )

    return access_token, username, uuid


async def _refresh_and_update_tokens(
    username: str,
    refresh_token: str,
    uuid: str,
) -> tuple[str, str]:
    """Helper function to refresh tokens and update storage."""
    result = await ms.login_with_refresh_token(refresh_token)
    access_token = result["access_token"]
    new_refresh_token = result["refresh_token"]

    if new_refresh_token:
        auth_data = f"{access_token} {new_refresh_token} {uuid}"
        safe_set("proxhy", username, auth_data)
        return access_token, new_refresh_token
    else:
        return access_token, refresh_token


async def login_with_refresh_token(refresh_token: str) -> tuple[str, str, str]:
    """
    Login using a refresh token.

    Args:
        refresh_token: The refresh token from a previous login

    Returns:
        Tuple of (access_token, username, uuid)
    """
    result = await ms.login_with_refresh_token(refresh_token)

    access_token = result["access_token"]
    username = result["username"]
    uuid = result["uuid"]
    new_refresh_token = result["refresh_token"]

    # Cache the new credentials
    auth_data = f"{access_token} {new_refresh_token} {uuid}"
    safe_set("proxhy", username, auth_data)

    return access_token, username, uuid


def refresh_access_token(refresh_token: str) -> str:
    """
    Refresh a Microsoft access token synchronously.

    Note: Prefer async auth.login_with_refresh_token() when possible.

    Args:
        refresh_token: The refresh token

    Returns:
        New access token
    """
    import asyncio

    async def _refresh():
        return await ms.refresh_ms_token(refresh_token)

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            raise RuntimeError(
                "refresh_access_token cannot be called from async context. "
                "Use await auth.ms.refresh_ms_token() directly."
            )
        result = loop.run_until_complete(_refresh())
    except RuntimeError:
        result = asyncio.run(_refresh())

    return result["access_token"]
