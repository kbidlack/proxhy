import os
import time

import jwt
import keyring

import auth


async def login(email: str, password: str) -> tuple[str, str, str]:
    """Login with email/password and cache the refresh token."""
    result = await auth.login(email, password)
    access_token = result["access_token"]
    username = result["username"]
    uuid = result["uuid"]
    refresh_token = result["refresh_token"]

    # Save auth info using refresh token
    auth_data = f"{access_token} {refresh_token} {uuid}"
    safe_set("proxhy", username, auth_data)

    return access_token, username, uuid


def user_exists(username: str) -> bool:
    return keyring.get_password("proxhy", username) is not None


# https://pypi.org/project/msmcauthaio/
# just kidding not anymore!! now we use our own auth library because we're cool
# and got chatgpt to make it for us (sunglasses emoji)
async def load_auth_info(username: str = "") -> tuple[str, str, str]:
    """Load cached auth info and refresh token if needed."""
    record = keyring.get_password("proxhy", username)
    if record is None:
        raise RuntimeError(f"No cached credentials for user {username!r}")

    parts = record.split(" ")
    if len(parts) != 3:
        raise RuntimeError(f"Invalid cached credential format for user {username!r}")

    access_token, refresh_token, uuid = parts

    # Check if token needs refreshing (older than 23 hours)
    try:
        iat = jwt.decode(
            access_token, algorithms=["HS256"], options={"verify_signature": False}
        )["iat"]
        token_age = time.time() - float(iat)

        if token_age > 82_800:  # 23 hours in seconds
            access_token, refresh_token = await _refresh_and_update_tokens(
                username, refresh_token, uuid
            )

    except (jwt.InvalidTokenError, KeyError, ValueError):
        # If token is malformed, try to refresh
        access_token, refresh_token = await _refresh_and_update_tokens(
            username, refresh_token, uuid
        )

    return access_token, username, uuid


async def _refresh_and_update_tokens(
    username: str, refresh_token: str, uuid: str
) -> tuple[str, str]:
    """Helper function to refresh tokens and update storage."""
    try:
        result = await auth.login_with_refresh_token(refresh_token)
        access_token = result["access_token"]
        new_refresh_token = result["refresh_token"]

        # Update stored credentials with new tokens
        if new_refresh_token:
            auth_data = f"{access_token} {new_refresh_token} {uuid}"
            safe_set("proxhy", username, auth_data)
            return access_token, new_refresh_token
        else:
            return access_token, refresh_token

    except Exception:
        raise RuntimeError(
            f"Failed to refresh token for user {username!r}. Manual re-login required."
        )


# ---------- CRED-SIZE GUARD ----------
MAX_SECRET_CHARS = 1_250  # ≈2 500 bytes in the Windows vault


def safe_set(service: str, user: str, secret: str) -> None:
    """
    Write to the keyring unless the secret is too large for Windows
    Credential Manager's 2 560-byte blob limit.  Raises ValueError
    early instead of letting win32cred.CredWrite explode later.
    """
    if len(secret) > MAX_SECRET_CHARS and os.name == "nt":
        raise ValueError(
            f"Secret for {service}/{user} is too large "
            f"({len(secret)} > {MAX_SECRET_CHARS} characters)."
        )
    keyring.set_password(service, user, secret)


# -------------------------------------


def refresh_access_token(refresh_token: str) -> str:
    """
    Refresh a Microsoft access token using the refresh token.

    This function is now implemented using the auth module's refresh functionality.
    """
    import asyncio

    async def _refresh():
        return await auth.refresh_ms_token(refresh_token)

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
