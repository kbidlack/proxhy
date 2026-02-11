"""
Microsoft Authentication for Minecraft.

This module implements the Microsoft OAuth2 authentication flow for Minecraft
using the Azure AD device code flow (recommended) or authorization code flow.

Based on:
- https://wiki.vg/Microsoft_Authentication_Scheme
- https://codeberg.org/JakobDev/minecraft-launcher-lib

Flow:
1. Get device code from Azure AD
2. User authenticates at microsoft.com/link
3. Poll for access token
4. Authenticate with Xbox Live
5. Get XSTS token
6. Authenticate with Minecraft
7. Verify game ownership and get profile
"""

import secrets
import time
from typing import TYPE_CHECKING, TypedDict
from urllib.parse import parse_qs, urlencode, urlparse

import aiohttp

from .errors import AuthException, InvalidCredentials, NotPremium

if TYPE_CHECKING:
    from collections.abc import Callable


class LoginResult(TypedDict):
    """Result of a successful login operation."""

    access_token: str
    username: str
    uuid: str
    refresh_token: str


class DeviceCodeResponse(TypedDict):
    """Response from device code request."""

    user_code: str
    device_code: str
    verification_uri: str
    expires_in: int
    interval: int
    message: str


class SecureLoginData(TypedDict):
    """Secure login data with PKCE and state parameters."""

    login_url: str
    state: str
    code_verifier: str


# Azure AD OAuth2 endpoints
AZURE_TOKEN_URL = "https://login.microsoftonline.com/consumers/oauth2/v2.0/token"
AZURE_AUTHORIZE_URL = (
    "https://login.microsoftonline.com/consumers/oauth2/v2.0/authorize"
)
AZURE_DEVICE_CODE_URL = (
    "https://login.microsoftonline.com/consumers/oauth2/v2.0/devicecode"
)

# Xbox and Minecraft endpoints
XBL_AUTH_URL = "https://user.auth.xboxlive.com/user/authenticate"
XSTS_AUTH_URL = "https://xsts.auth.xboxlive.com/xsts/authorize"
MC_LOGIN_URL = "https://api.minecraftservices.com/authentication/login_with_xbox"
MC_ENTITLEMENTS_URL = "https://api.minecraftservices.com/entitlements/mcstore"
MC_PROFILE_URL = "https://api.minecraftservices.com/minecraft/profile"

# OAuth2 scopes
SCOPE = "XboxLive.signin offline_access"

# Default timeout
DEFAULT_TIMEOUT = 30.0


def get_login_url(client_id: str, redirect_uri: str) -> str:
    """
    Generate a Microsoft OAuth2 login URL.

    Args:
        client_id: Your Azure application client ID
        redirect_uri: The redirect URI configured in your Azure app

    Returns:
        The URL to redirect users to for login
    """
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": SCOPE,
        "response_mode": "query",
    }
    return f"{AZURE_AUTHORIZE_URL}?{urlencode(params)}"


def get_secure_login_data(client_id: str, redirect_uri: str) -> SecureLoginData:
    """
    Generate secure login data with PKCE and state parameters.

    This is the recommended approach as it prevents CSRF and authorization
    code injection attacks.

    Args:
        client_id: Your Azure application client ID
        redirect_uri: The redirect URI configured in your Azure app

    Returns:
        Dictionary containing login_url, state, and code_verifier
    """
    import base64
    import hashlib

    state = generate_state()
    code_verifier = secrets.token_urlsafe(32)

    # Generate code_challenge from code_verifier
    code_challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest())
        .decode()
        .rstrip("=")
    )

    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": SCOPE,
        "response_mode": "query",
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }

    return {
        "login_url": f"{AZURE_AUTHORIZE_URL}?{urlencode(params)}",
        "state": state,
        "code_verifier": code_verifier,
    }


def generate_state() -> str:
    """Generate a random state string for CSRF protection."""
    return secrets.token_urlsafe(16)


def url_contains_auth_code(url: str) -> bool:
    """Check if a URL contains an authorization code."""
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    return "code" in params


def parse_auth_code_url(url: str, expected_state: str | None = None) -> str:
    """
    Extract the authorization code from a redirect URL.

    Args:
        url: The redirect URL containing the code
        expected_state: If provided, verify the state parameter matches

    Returns:
        The authorization code

    Raises:
        AuthException: If code is missing or state doesn't match
    """
    parsed = urlparse(url)
    params = parse_qs(parsed.query)

    if "error" in params:
        error = params["error"][0]
        description = params.get("error_description", ["Unknown error"])[0]
        raise AuthException(
            f"OAuth error: {error} - {description}",
            code="OAUTH-ERROR",
        )

    if "code" not in params:
        raise AuthException(
            "Authorization code not found in URL",
            code="OAUTH-NO-CODE",
        )

    if expected_state is not None:
        state = params.get("state", [None])[0]
        if state != expected_state:
            raise AuthException(
                "State parameter mismatch (possible CSRF attack)",
                code="OAUTH-STATE-MISMATCH",
            )

    return params["code"][0]


async def request_device_code(
    client_id: str,
    timeout: float = DEFAULT_TIMEOUT,
) -> DeviceCodeResponse:
    """
    Request a device code for the device code flow.

    This is the recommended flow for CLI applications. The user will be
    prompted to visit a URL and enter a code.

    Args:
        client_id: Your Azure application client ID
        timeout: Request timeout in seconds

    Returns:
        Dictionary containing user_code, device_code, verification_uri, etc.
    """
    data = {
        "client_id": client_id,
        "scope": SCOPE,
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            AZURE_DEVICE_CODE_URL,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as resp:
            if not resp.ok:
                text = await resp.text()
                raise AuthException(
                    f"Failed to request device code: {resp.status}",
                    code="DEVICE-CODE-FAILED",
                    detail=text,
                )

            result = await resp.json()
            return {
                "user_code": result["user_code"],
                "device_code": result["device_code"],
                "verification_uri": result["verification_uri"],
                "expires_in": result["expires_in"],
                "interval": result["interval"],
                "message": result.get(
                    "message",
                    f"Go to {result['verification_uri']} and enter code: {result['user_code']}",
                ),
            }


async def poll_device_code(
    client_id: str,
    device_code: str,
    interval: int = 5,
    expires_in: int = 900,
    timeout: float = DEFAULT_TIMEOUT,
    on_pending: Callable[[], None] | None = None,
) -> dict[str, str]:
    """
    Poll for the device code authentication result.

    Args:
        client_id: Your Azure application client ID
        device_code: The device code from request_device_code
        interval: Polling interval in seconds
        expires_in: When the device code expires
        timeout: Request timeout in seconds
        on_pending: Optional callback called while waiting for user

    Returns:
        Dictionary containing access_token and refresh_token
    """
    start_time = time.time()

    data = {
        "client_id": client_id,
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        "device_code": device_code,
    }

    async with aiohttp.ClientSession() as session:
        while True:
            if time.time() - start_time > expires_in:
                raise AuthException(
                    "Device code expired",
                    code="DEVICE-CODE-EXPIRED",
                )

            async with session.post(
                AZURE_TOKEN_URL,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                result = await resp.json()

                if resp.ok:
                    return {
                        "access_token": result["access_token"],
                        "refresh_token": result.get("refresh_token", ""),
                    }

                error = result.get("error", "")

                if error == "authorization_pending":
                    if on_pending:
                        on_pending()
                    await _async_sleep(interval)
                    continue
                elif error == "slow_down":
                    interval += 5
                    await _async_sleep(interval)
                    continue
                elif error == "authorization_declined":
                    raise AuthException(
                        "User declined authorization",
                        code="DEVICE-CODE-DECLINED",
                    )
                elif error == "expired_token":
                    raise AuthException(
                        "Device code expired",
                        code="DEVICE-CODE-EXPIRED",
                    )
                else:
                    description = result.get("error_description", "Unknown error")
                    raise AuthException(
                        f"Device code polling failed: {description}",
                        code="DEVICE-CODE-FAILED",
                        detail=str(result),
                    )


async def _async_sleep(seconds: float) -> None:
    """Async sleep helper."""
    import asyncio

    await asyncio.sleep(seconds)


async def get_authorization_token(
    client_id: str,
    redirect_uri: str,
    auth_code: str,
    code_verifier: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, str]:
    """
    Exchange an authorization code for tokens.

    Args:
        client_id: Your Azure application client ID
        redirect_uri: The redirect URI used in the authorization request
        auth_code: The authorization code from the redirect
        code_verifier: The PKCE code verifier (if using secure login)
        timeout: Request timeout in seconds

    Returns:
        Dictionary containing access_token and refresh_token
    """
    data = {
        "client_id": client_id,
        "grant_type": "authorization_code",
        "code": auth_code,
        "redirect_uri": redirect_uri,
        "scope": SCOPE,
    }

    if code_verifier:
        data["code_verifier"] = code_verifier

    async with aiohttp.ClientSession() as session:
        async with session.post(
            AZURE_TOKEN_URL,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as resp:
            if not resp.ok:
                result = await resp.json()
                error = result.get("error", "unknown")
                description = result.get("error_description", "")
                raise AuthException(
                    f"Failed to get authorization token: {error}",
                    code="OAUTH-TOKEN-FAILED",
                    detail=description,
                )

            result = await resp.json()
            return {
                "access_token": result["access_token"],
                "refresh_token": result.get("refresh_token", ""),
            }


async def refresh_authorization_token(
    client_id: str,
    refresh_token: str,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, str]:
    """
    Refresh an access token using a refresh token.

    Args:
        client_id: Your Azure application client ID
        refresh_token: The refresh token from a previous login
        timeout: Request timeout in seconds

    Returns:
        Dictionary containing access_token and refresh_token
    """
    data = {
        "client_id": client_id,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "scope": SCOPE,
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            AZURE_TOKEN_URL,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as resp:
            if resp.status == 400:
                try:
                    result = await resp.json()
                    error = result.get("error", "")
                    if error in ("invalid_grant", "expired_token"):
                        raise InvalidCredentials(
                            "Refresh token is invalid or expired",
                            code="MSA-REFRESH-EXPIRED",
                        )
                except InvalidCredentials:
                    raise
                except Exception:
                    pass
                raise InvalidCredentials(
                    "Failed to refresh token",
                    code="MSA-REFRESH-INVALID",
                )

            if not resp.ok:
                text = await resp.text()
                raise AuthException(
                    f"Token refresh failed: {resp.status}",
                    code="MSA-REFRESH-FAILED",
                    detail=text,
                )

            result = await resp.json()
            return {
                "access_token": result["access_token"],
                "refresh_token": result.get("refresh_token", ""),
            }


async def authenticate_with_xbl(
    access_token: str,
    timeout: float = DEFAULT_TIMEOUT,
) -> tuple[str, str]:
    """
    Authenticate with Xbox Live using a Microsoft access token.

    Args:
        access_token: Microsoft OAuth2 access token
        timeout: Request timeout in seconds

    Returns:
        Tuple of (xbl_token, user_hash)
    """
    payload = {
        "Properties": {
            "AuthMethod": "RPS",
            "SiteName": "user.auth.xboxlive.com",
            "RpsTicket": f"d={access_token}",
        },
        "RelyingParty": "http://auth.xboxlive.com",
        "TokenType": "JWT",
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            XBL_AUTH_URL,
            json=payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as resp:
            if not resp.ok:
                text = await resp.text()
                raise AuthException(
                    f"Xbox Live authentication failed: {resp.status}",
                    code="XBL-FAILED",
                    detail=text,
                )

            data = await resp.json()
            token = data.get("Token")

            try:
                user_hash = data["DisplayClaims"]["xui"][0]["uhs"]
            except (KeyError, IndexError) as e:
                raise AuthException(
                    f"Xbox Live response missing user hash: {e}",
                    code="XBL-MALFORMED",
                )

            if not token:
                raise AuthException(
                    "Xbox Live response missing token",
                    code="XBL-MALFORMED",
                )

            return token, user_hash


async def authenticate_with_xsts(
    xbl_token: str,
    timeout: float = DEFAULT_TIMEOUT,
) -> tuple[str, str]:
    """
    Get an XSTS token using an Xbox Live token.

    Args:
        xbl_token: Xbox Live token from authenticate_with_xbl
        timeout: Request timeout in seconds

    Returns:
        Tuple of (xsts_token, user_hash)
    """
    payload = {
        "Properties": {
            "SandboxId": "RETAIL",
            "UserTokens": [xbl_token],
        },
        "RelyingParty": "rp://api.minecraftservices.com/",
        "TokenType": "JWT",
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            XSTS_AUTH_URL,
            json=payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as resp:
            if resp.status == 401:
                data = await resp.json()
                xerr = data.get("XErr")

                error_messages = {
                    2148916227: "This account has been banned from Xbox",
                    2148916233: "No Xbox account exists. Sign in to Xbox first.",
                    2148916235: "Xbox Live is not available in your region",
                    2148916236: "Adult verification required (South Korea)",
                    2148916237: "Adult verification required (South Korea)",
                    2148916238: "Child account must be added to a Family",
                }

                message = error_messages.get(xerr, "XSTS authorization failed")
                raise AuthException(message, code=f"XSTS-{xerr or 401}")

            if not resp.ok:
                text = await resp.text()
                raise AuthException(
                    f"XSTS authorization failed: {resp.status}",
                    code="XSTS-FAILED",
                    detail=text,
                )

            data = await resp.json()
            token = data.get("Token")

            try:
                user_hash = data["DisplayClaims"]["xui"][0]["uhs"]
            except (KeyError, IndexError) as e:
                raise AuthException(
                    f"XSTS response missing user hash: {e}",
                    code="XSTS-MALFORMED",
                )

            if not token:
                raise AuthException(
                    "XSTS response missing token",
                    code="XSTS-MALFORMED",
                )

            return token, user_hash


async def authenticate_with_minecraft(
    user_hash: str,
    xsts_token: str,
    timeout: float = DEFAULT_TIMEOUT,
) -> str:
    """
    Authenticate with Minecraft using XSTS credentials.

    Args:
        user_hash: User hash from XSTS authentication
        xsts_token: XSTS token
        timeout: Request timeout in seconds

    Returns:
        Minecraft access token
    """
    payload = {
        "identityToken": f"XBL3.0 x={user_hash};{xsts_token}",
        "ensureLegacyEnabled": True,
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            MC_LOGIN_URL,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as resp:
            if not resp.ok:
                text = await resp.text()
                raise AuthException(
                    f"Minecraft authentication failed: {resp.status}",
                    code="MC-LOGIN-FAILED",
                    detail=text,
                )

            data = await resp.json()
            access_token = data.get("access_token")

            if not access_token:
                raise AuthException(
                    "Minecraft response missing access token",
                    code="MC-LOGIN-MALFORMED",
                )

            return access_token


async def check_ownership(
    mc_access_token: str,
    timeout: float = DEFAULT_TIMEOUT,
) -> bool:
    """
    Check if the account owns Minecraft: Java Edition.

    Args:
        mc_access_token: Minecraft access token
        timeout: Request timeout in seconds

    Returns:
        True if the account owns the game
    """
    async with aiohttp.ClientSession() as session:
        async with session.get(
            MC_ENTITLEMENTS_URL,
            headers={"Authorization": f"Bearer {mc_access_token}"},
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as resp:
            if not resp.ok:
                text = await resp.text()
                raise AuthException(
                    f"Entitlements check failed: {resp.status}",
                    code="MC-ENTITLEMENTS-FAILED",
                    detail=text,
                )

            data = await resp.json()
            items = data.get("items", [])

            # Check for Minecraft Java Edition ownership
            java_products = ("product_minecraft", "game_minecraft")
            return any(item.get("name") in java_products for item in items) or bool(
                items
            )  # Fallback: any items means some ownership


async def get_profile(
    mc_access_token: str,
    timeout: float = DEFAULT_TIMEOUT,
) -> tuple[str, str]:
    """
    Get the Minecraft profile (username and UUID).

    Args:
        mc_access_token: Minecraft access token
        timeout: Request timeout in seconds

    Returns:
        Tuple of (username, uuid)
    """
    async with aiohttp.ClientSession() as session:
        async with session.get(
            MC_PROFILE_URL,
            headers={"Authorization": f"Bearer {mc_access_token}"},
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as resp:
            if resp.status == 404:
                raise NotPremium(
                    "Minecraft profile not found. Account may not own Java Edition.",
                    code="MC-NOT-PREMIUM",
                )

            if not resp.ok:
                text = await resp.text()
                raise AuthException(
                    f"Failed to get Minecraft profile: {resp.status}",
                    code="MC-PROFILE-FAILED",
                    detail=text,
                )

            data = await resp.json()
            username = data.get("name", "")
            uuid = data.get("id", "")

            if not username or not uuid:
                raise AuthException(
                    "Minecraft profile incomplete (missing name/id)",
                    code="MC-PROFILE-INCOMPLETE",
                )

            return username, uuid


async def complete_login(
    client_id: str,
    ms_access_token: str,
    ms_refresh_token: str = "",
) -> LoginResult:
    """
    Complete the full Minecraft authentication after obtaining Microsoft tokens.

    This handles the Xbox Live -> XSTS -> Minecraft flow.

    Args:
        client_id: Your Azure application client ID (for future refresh)
        ms_access_token: Microsoft OAuth2 access token
        ms_refresh_token: Microsoft OAuth2 refresh token

    Returns:
        LoginResult with Minecraft access_token, username, uuid, and refresh_token
    """
    # Xbox Live authentication
    xbl_token, _ = await authenticate_with_xbl(ms_access_token)

    # XSTS token
    xsts_token, user_hash = await authenticate_with_xsts(xbl_token)

    # Minecraft authentication
    mc_access_token = await authenticate_with_minecraft(user_hash, xsts_token)

    # Verify ownership
    if not await check_ownership(mc_access_token):
        raise NotPremium(
            "This account does not own Minecraft: Java Edition",
            code="MC-NOT-PREMIUM",
        )

    # Get profile
    username, uuid = await get_profile(mc_access_token)

    return {
        "access_token": mc_access_token,
        "username": username,
        "uuid": uuid,
        "refresh_token": ms_refresh_token,
    }


async def complete_refresh(
    client_id: str,
    refresh_token: str,
) -> LoginResult:
    """
    Refresh authentication using a stored refresh token.

    Args:
        client_id: Your Azure application client ID
        refresh_token: The refresh token from a previous login

    Returns:
        LoginResult with new tokens and profile
    """
    # Refresh Microsoft token
    tokens = await refresh_authorization_token(client_id, refresh_token)

    # Complete login with new tokens
    return await complete_login(
        client_id,
        tokens["access_token"],
        tokens["refresh_token"],
    )


# ============================================================================
# Legacy API compatibility
# ============================================================================

# Default client ID - users should provide their own
_DEFAULT_CLIENT_ID: str | None = None


def set_client_id(client_id: str) -> None:
    """
    Set the default Azure client ID for authentication.

    This must be called before using login() or login_with_refresh_token().

    Args:
        client_id: Your Azure application client ID
    """
    global _DEFAULT_CLIENT_ID
    _DEFAULT_CLIENT_ID = client_id


def get_client_id() -> str:
    """Get the configured client ID or raise an error."""
    if _DEFAULT_CLIENT_ID is None:
        raise AuthException(
            "No client ID configured. Call auth.ms.set_client_id() first.",
            code="NO-CLIENT-ID",
        )
    return _DEFAULT_CLIENT_ID


async def login(email: str, password: str) -> LoginResult:
    """
    Legacy login function - NOT SUPPORTED with Azure OAuth2.

    Microsoft no longer supports password-based authentication for consumer
    accounts through Azure AD. Use the device code flow instead.

    Args:
        email: Ignored
        password: Ignored

    Raises:
        AuthException: Always raises explaining the migration
    """
    raise AuthException(
        "Password-based login is no longer supported. "
        "Use the device code flow: await auth.ms.request_device_code(client_id)",
        code="PASSWORD-LOGIN-DEPRECATED",
    )


async def login_with_refresh_token(refresh_token: str) -> LoginResult:
    """
    Login using a refresh token.

    Requires set_client_id() to be called first.

    Args:
        refresh_token: The refresh token from a previous login

    Returns:
        LoginResult with new tokens and profile
    """
    client_id = get_client_id()
    return await complete_refresh(client_id, refresh_token)


async def refresh_ms_token(refresh_token: str) -> dict[str, str]:
    """
    Refresh a Microsoft access token.

    Requires set_client_id() to be called first.

    Args:
        refresh_token: The refresh token from a previous login

    Returns:
        Dictionary containing access_token and refresh_token
    """
    client_id = get_client_id()
    return await refresh_authorization_token(client_id, refresh_token)
