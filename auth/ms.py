import os
import re
import time
from typing import Dict, TypedDict
from urllib.parse import parse_qsl, urlsplit

import aiohttp

from .errors import AuthException, InvalidCredentials, NotPremium


class LoginResult(TypedDict):
    """Result of a successful login operation."""

    access_token: str
    username: str
    uuid: str
    refresh_token: str


# Endpoints
_LIVE_AUTHORIZE = (
    "https://login.live.com/oauth20_authorize.srf"
    "?client_id=000000004C12AE6F"
    "&redirect_uri=https://login.live.com/oauth20_desktop.srf"
    "&scope=service::user.auth.xboxlive.com::MBI_SSL"
    "&response_type=token"
    "&prompt=login"
    "&mkt=en-US"
)


_XBL_USER_AUTH = "https://user.auth.xboxlive.com/user/authenticate"
_XSTS_AUTHORIZE = "https://xsts.auth.xboxlive.com/xsts/authorize"
_MC_LOGIN_WITH_XBOX = "https://api.minecraftservices.com/authentication/login_with_xbox"
_MC_ENTITLEMENTS = "https://api.minecraftservices.com/entitlements/mcstore"
_MC_PROFILE = "https://api.minecraftservices.com/minecraft/profile"
AUTH_DEBUG = 0  # set to 1 if you want to debug errors


def _dbg_dump(name: str, content: str | bytes) -> None:
    # Enable if either env var AUTH_DEBUG is set (not "0") OR the module constant AUTH_DEBUG is truthy
    enabled = os.getenv("AUTH_DEBUG")
    if enabled is None:
        enabled = globals().get("AUTH_DEBUG", 0)
    if not str(enabled) or str(enabled) == "0":
        return

    # Where to write: use DEBUG_PATH if you set it; otherwise use current working dir
    base = globals().get("DEBUG_PATH", None)
    if not base:
        base = os.getcwd()

    os.makedirs(base, exist_ok=True)  # ensure folder exists
    path = os.path.join(base, f"{int(time.time())}_{name}")

    mode = "wb" if isinstance(content, (bytes, bytearray)) else "w"
    with open(path, mode, encoding=None if mode == "wb" else "utf-8") as f:
        f.write(content)


def _extract_login_form(html: str) -> tuple[str, str]:
    """
    Extract PPFT and urlPost from multiple known Microsoft variants.

    Tries, in order:
    - JSON-style: "sFTTag":{"value":"..."} and "urlPost":"https://..."
    - JS-style:   sFTTag:{value:'...'}    and urlPost:'https://...'
    - HTML form:  <input name="PPFT" value="..."> and <form ... method=post action="...">
    Then retries after unescaping \\u0026, \\u002F, and \\/ sequences commonly found in inline JSON.
    """

    _dbg_dump("authorize.html", html)

    def _try_extract(h: str) -> tuple[str | None, str | None]:
        ppft = urlpost = None

        # --- JSON-like ---
        if ppft is None:
            m = re.search(r'"sFTTag"\s*:\s*\{\s*"value"\s*:\s*"([^"]+)"', h)
            if m:
                ppft = m.group(1)
        if urlpost is None:
            m = re.search(r'"urlPost"\s*:\s*"([^"]+)"', h)
            if m:
                urlpost = m.group(1)

        # --- Double-escaped JSON (e.g., \" and \\/ ) ---
        if ppft is None:
            m = re.search(r'\\"sFTTag\\"\s*:\s*\{\s*\\"value\\"\s*:\s*\\"([^"]+)\\"', h)
            if m:
                ppft = m.group(1)
        if urlpost is None:
            m = re.search(r'\\"urlPost\\"\s*:\s*\\"([^"]+)\\"', h)
            if m:
                urlpost = m.group(1)

        # --- JS-like (single quotes) ---
        if ppft is None:
            m = re.search(r"sFTTag\s*:\s*\{\s*value\s*:\s*'([^']+)'", h)
            if m:
                ppft = m.group(1)
        if ppft is None:
            # very old inline pattern: sFTTag:'<input ... value="...">'
            m = re.search(r"sFTTag:\s*'[^>]*\bvalue=\"([^\"]+)\"", h)
            if m:
                ppft = m.group(1)
        if urlpost is None:
            m = re.search(r"urlPost\s*:\s*'([^']+)'", h)
            if m:
                urlpost = m.group(1)

        # --- HTML form fallbacks ---
        if ppft is None:
            m = re.search(r'name="PPFT"[^>]*value="([^"]+)"', h, flags=re.I)
            if m:
                ppft = m.group(1)
        if urlpost is None:
            # Prefer POST action
            m = re.search(
                r'<form[^>]+method=["\']post["\'][^>]*action=["\']([^"\']+)["\']',
                h,
                flags=re.I,
            )
            if m:
                urlpost = m.group(1)
        if urlpost is None:
            # Any form action as last resort
            m = re.search(r'<form[^>]*action=["\']([^"\']+)["\']', h, flags=re.I)
            if m:
                urlpost = m.group(1)

        # --- super loose fallback just in case: look for ppsecure/post.srf in the page ---
        if urlpost is None:
            m = re.search(r'https://login\.live\.com/ppsecure/post\.srf[^"\'<> ]*', h)
            if m:
                urlpost = m.group(0)

        return ppft, urlpost

    ppft, urlpost = _try_extract(html)

    # Retry after unescaping common inline escapes
    if not (ppft and urlpost):
        unescaped = (
            html.replace("\\u0026", "&")
            .replace("\\u002F", "/")
            .replace("\\/", "/")
            .replace('\\"', '"')
        )
        ppft, urlpost = _try_extract(unescaped)

    if not (ppft and urlpost):
        raise AuthException(
            "Could not locate PPFT/urlPost on authorize page.",
            code="MSA-FORM-PARSE",
            detail="Tried JSON/JS/HTML + unescaped variants; also ppsecure/post.srf fallback.",
        )
    return ppft, urlpost


def _parse_fragment(url: str) -> Dict[str, str]:
    if "#" not in url:
        return {}
    frag = url.split("#", 1)[1]
    parsed = dict(parse_qsl(frag))
    # URL decode the tokens if present
    if "access_token" in parsed:
        from urllib.parse import unquote

        parsed["access_token"] = unquote(parsed["access_token"])
    if "refresh_token" in parsed:
        from urllib.parse import unquote

        parsed["refresh_token"] = unquote(parsed["refresh_token"])
    return parsed


async def _follow_for_fragment(
    session: aiohttp.ClientSession, start_url: str, timeout: float
) -> Dict[str, str]:
    # Follow up to 10 redirects without auto-redirects so we can read Location fragments.
    url = start_url
    for _ in range(10):
        async with session.get(
            url, timeout=aiohttp.ClientTimeout(total=timeout), allow_redirects=False
        ) as r:
            loc = r.headers.get("Location")
            if not loc:
                if r.headers.get("Content-Type", "").startswith("text/html"):
                    html = await r.text()
                    _dbg_dump("desktop_srf.html", html)
                    m = re.search(r"access_token=([^&\"'<>]+)", html)
                    if m:
                        result = {"access_token": m.group(1)}
                        # Also look for refresh token
                        m_refresh = re.search(r"refresh_token=([^&\"'<>]+)", html)
                        if m_refresh:
                            result["refresh_token"] = m_refresh.group(1)
                        return result
                break
            if "#" in loc and "access_token=" in loc:
                return _parse_fragment(loc)
            if not loc.lower().startswith("http"):
                parts = urlsplit(url)
                loc = f"{parts.scheme}://{parts.netloc}{loc}"
            url = loc
    return {}


def _looks_like_password_error(text: str) -> bool:
    needles = [
        "Your account or password is incorrect",
        "That Microsoft account doesn't exist",
        "Enter a valid email address",
    ]
    text_lower = text.lower()
    return any(n.lower() in text_lower for n in needles)


def _looks_like_interactive_challenge(text: str) -> bool:
    needles = [
        "Help us protect your account",
        "Microsoft Authenticator",
        "Enter code",
        "We've sent a sign-in request",
        "Stay signed in?",
        "kmsi",
        "Approve sign in",
        "Verify your identity",
    ]
    text_lower = text.lower()
    return any(n.lower() in text_lower for n in needles)


async def _ms_login_with_password(
    email: str, password: str, timeout: float = 30.0
) -> Dict[str, str]:
    async with aiohttp.ClientSession(
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept-Language": "en-US,en;q=0.9",
        }
    ) as session:
        async with session.get(
            _LIVE_AUTHORIZE, timeout=aiohttp.ClientTimeout(total=timeout)
        ) as r:
            r.raise_for_status()
            html = await r.text()
            ppft, urlpost = _extract_login_form(html)

        data = {"login": email, "loginfmt": email, "passwd": password, "PPFT": ppft}
        async with session.post(
            urlpost, data=data, timeout=aiohttp.ClientTimeout(total=timeout)
        ) as r2:
            txt = await r2.text() or ""
            _dbg_dump("post_resp.html", txt)

            if _looks_like_password_error(txt):
                raise InvalidCredentials(
                    "Your account or password is incorrect.", code="MSA-WRONG-PASSWORD"
                )

            if _looks_like_interactive_challenge(txt):
                # Cannot complete interactive steps in a headless/password-only flow.
                raise InvalidCredentials(
                    "Account requires interactive verification (2FA/KMSI/CAPTCHA).",
                    code="MSA-INTERACTIVE",
                )

            # 1) Check redirect history for a fragment
            for h in list(r2.history) + [r2]:
                loc = getattr(h, "headers", {}).get("Location")
                if loc and "#" in loc and "access_token=" in loc:
                    return _parse_fragment(loc)

            # 2) Check the URL itself
            if "#" in str(r2.url):
                frag = _parse_fragment(str(r2.url))
                if "access_token" in frag:
                    return frag

            # 3) Manually re-follow to capture Location fragments
            frag = await _follow_for_fragment(session, _LIVE_AUTHORIZE, timeout=timeout)
            if "access_token" in frag:
                return frag

            # No token visible
            raise AuthException(
                "Microsoft login finished without returning an access_token.",
                code="MSA-NO-TOKEN",
            )


async def refresh_ms_token(refresh_token: str, timeout: float = 30.0) -> Dict[str, str]:
    """
    Refresh a Microsoft access token using a refresh token.

    Args:
        refresh_token: The refresh token obtained from a previous login
        timeout: Request timeout in seconds

    Returns:
        Dictionary containing the new access_token and potentially a new refresh_token

    Raises:
        AuthException: If the refresh fails
        InvalidCredentials: If the refresh token is invalid
    """
    # For the password flow, we need to use the token refresh endpoint
    refresh_url = "https://login.live.com/oauth20_token.srf"

    data = {
        "client_id": "000000004C12AE6F",
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "redirect_uri": "https://login.live.com/oauth20_desktop.srf",
        "scope": "service::user.auth.xboxlive.com::MBI_SSL",
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            refresh_url,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as r:
            if r.status == 400:
                try:
                    error_data = await r.json()
                    error_desc = error_data.get("error_description", "")
                    if (
                        "invalid_grant" in error_desc.lower()
                        or "expired" in error_desc.lower()
                    ):
                        raise InvalidCredentials(
                            "Refresh token is invalid or expired.",
                            code="MSA-REFRESH-EXPIRED",
                        )
                except Exception:
                    pass
                raise InvalidCredentials(
                    "Failed to refresh token: invalid refresh token.",
                    code="MSA-REFRESH-INVALID",
                )

            if not r.ok:
                try:
                    detail = await r.json()
                except Exception:
                    detail = await r.text()
                raise AuthException(
                    f"Token refresh failed: {r.status}",
                    code="MSA-REFRESH-FAILED",
                    detail=str(detail),
                )

            data = await r.json()
            result = {}

            if "access_token" in data:
                result["access_token"] = data["access_token"]
            if "refresh_token" in data:
                result["refresh_token"] = data["refresh_token"]

            if not result.get("access_token"):
                raise AuthException(
                    "Refresh response missing access_token.",
                    code="MSA-REFRESH-MALFORMED",
                )

            return result


async def _xbox_live_auth(
    ms_access_token: str, timeout: float = 15.0
) -> tuple[str, str]:
    async def do_req(
        session: aiohttp.ClientSession, ticket: str
    ) -> aiohttp.ClientResponse:
        payload = {
            "Properties": {
                "AuthMethod": "RPS",
                "SiteName": "user.auth.xboxlive.com",
                "RpsTicket": ticket,
            },
            "RelyingParty": "http://auth.xboxlive.com",
            "TokenType": "JWT",
        }
        return await session.post(
            _XBL_USER_AUTH,
            json=payload,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            timeout=aiohttp.ClientTimeout(total=timeout),
        )

    async with aiohttp.ClientSession() as session:
        last_response = None
        for ticket in (f"d={ms_access_token}", ms_access_token):
            async with await do_req(session, ticket) as r:
                last_response = r
                if r.ok:
                    data = await r.json()
                    token = data.get("Token")
                    try:
                        uhs = data["DisplayClaims"]["xui"][0]["uhs"]
                    except Exception as e:
                        raise AuthException(
                            f"Xbox Live response missing user hash: {e}",
                            code="XBL-MALFORMED",
                        )
                    if not token or not uhs:
                        raise AuthException(
                            "Xbox Live response missing token/uhs.",
                            code="XBL-MALFORMED",
                        )
                    return token, uhs

        try:
            detail = await last_response.json() if last_response else None
        except Exception:
            detail = await last_response.text() if last_response else "no response"
        raise AuthException(
            "Xbox Live authentication failed.", code="XBL-FAILED", detail=str(detail)
        )


async def _xsts_authorize(xbl_token: str, timeout: float = 15.0) -> tuple[str, str]:
    payload = {
        "Properties": {"SandboxId": "RETAIL", "UserTokens": [xbl_token]},
        "RelyingParty": "rp://api.minecraftservices.com/",
        "TokenType": "JWT",
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(
            _XSTS_AUTHORIZE,
            json=payload,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as r:
            if r.status == 401:
                try:
                    data = await r.json()
                    xerr = data.get("XErr")
                except Exception:
                    xerr = None
                if xerr == 2148916238:
                    raise AuthException(
                        "Xbox Live: child account; must be added to a family.",
                        code="XSTS-CHILD",
                    )
                if xerr == 2148916233:
                    raise AuthException(
                        "Xbox Live: no Xbox profile; sign in to Xbox once then retry.",
                        code="XSTS-NOPROFILE",
                    )
                raise AuthException("XSTS authorization failed (401).", code="XSTS-401")
            r.raise_for_status()
            data = await r.json()
            token = data.get("Token")
            try:
                uhs = data["DisplayClaims"]["xui"][0]["uhs"]
            except Exception as e:
                raise AuthException(
                    f"XSTS response missing user hash: {e}", code="XSTS-MALFORMED"
                )
            if not token:
                raise AuthException(
                    "XSTS response missing token.", code="XSTS-MALFORMED"
                )
            return token, uhs


async def _mc_login_with_xbox(uhs: str, xsts_token: str, timeout: float = 15.0) -> str:
    ident = f"XBL3.0 x={uhs};{xsts_token}"
    payload = {"identityToken": ident, "ensureLegacyEnabled": True}
    async with aiohttp.ClientSession() as session:
        async with session.post(
            _MC_LOGIN_WITH_XBOX,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as r:
            if not r.ok:
                error_text = await r.text()
                raise AuthException(
                    f"Minecraft login_with_xbox failed: {r.status}",
                    code="MC-LOGIN",
                    detail=error_text,
                )
            data = await r.json()
            access = data.get("access_token")
            if not access:
                raise AuthException(
                    "Minecraft login did not return access_token.",
                    code="MC-LOGIN-MALFORMED",
                )
            return access


async def _mc_check_ownership(mc_access_token: str, timeout: float = 15.0) -> bool:
    async with aiohttp.ClientSession() as session:
        async with session.get(
            _MC_ENTITLEMENTS,
            headers={"Authorization": f"Bearer {mc_access_token}"},
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as r:
            if not r.ok:
                try:
                    detail = await r.json()
                except Exception:
                    detail = await r.text()
                raise AuthException(
                    "Entitlements check failed.",
                    code="MC-ENTITLEMENTS",
                    detail=str(detail),
                )
            data = await r.json()
            items = data.get("items") or []
            return any(
                it.get("name") in ("product_minecraft", "game_minecraft")
                for it in items
            ) or bool(items)


async def _mc_profile(mc_access_token: str, timeout: float = 15.0) -> tuple[str, str]:
    async with aiohttp.ClientSession() as session:
        async with session.get(
            _MC_PROFILE,
            headers={"Authorization": f"Bearer {mc_access_token}"},
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as r:
            if r.status == 404:
                raise NotPremium(
                    "Minecraft profile not found; account may not own Java Edition.",
                    code="MC-NOT-PREMIUM",
                )
            if not r.ok:
                try:
                    detail = await r.json()
                except Exception:
                    detail = await r.text()
                raise AuthException(
                    "Failed to fetch Minecraft profile.",
                    code="MC-PROFILE",
                    detail=str(detail),
                )
            data = await r.json()
            return data.get("name", ""), data.get("id", "")


async def login(email: str, password: str) -> LoginResult:
    """
    Login with Microsoft account credentials.

    Args:
        email: Microsoft account email
        password: Microsoft account password

    Returns:
        Dictionary containing:
        - access_token: Minecraft access token
        - username: Minecraft username
        - uuid: Minecraft UUID
        - refresh_token: Microsoft refresh token (may be empty if not provided)

    Raises:
        AuthException: If authentication fails
        InvalidCredentials: If credentials are invalid
        NotPremium: If the account doesn't own Minecraft
    """
    token_data = await _ms_login_with_password(email, password)
    xbl_token, _ = await _xbox_live_auth(token_data["access_token"])
    xsts_token, uhs = await _xsts_authorize(xbl_token)
    mc_access_token = await _mc_login_with_xbox(uhs, xsts_token)

    if not await _mc_check_ownership(mc_access_token):
        raise NotPremium(
            "This Microsoft account does not own Minecraft: Java Edition.",
            code="MC-NOT-PREMIUM",
        )

    username, uuid_ = await _mc_profile(mc_access_token)
    if not username or not uuid_:
        raise AuthException(
            "Minecraft profile incomplete (missing name/id).",
            code="MC-PROFILE-INCOMPLETE",
        )

    return {
        "access_token": mc_access_token,
        "username": username,
        "uuid": uuid_,
        "refresh_token": token_data.get("refresh_token", ""),
    }


async def login_with_refresh_token(refresh_token: str) -> LoginResult:
    """
    Login using a refresh token instead of email/password.

    Args:
        refresh_token: The refresh token from a previous login

    Returns:
        Dictionary containing:
        - access_token: Minecraft access token
        - username: Minecraft username
        - uuid: Minecraft UUID
        - refresh_token: New Microsoft refresh token (may be empty if not provided)

    Raises:
        AuthException: If authentication fails
        InvalidCredentials: If the refresh token is invalid
        NotPremium: If the account doesn't own Minecraft
    """
    token_data = await refresh_ms_token(refresh_token)
    xbl_token, _ = await _xbox_live_auth(token_data["access_token"])
    xsts_token, uhs = await _xsts_authorize(xbl_token)
    mc_access_token = await _mc_login_with_xbox(uhs, xsts_token)

    if not await _mc_check_ownership(mc_access_token):
        raise NotPremium(
            "This Microsoft account does not own Minecraft: Java Edition.",
            code="MC-NOT-PREMIUM",
        )

    username, uuid_ = await _mc_profile(mc_access_token)
    if not username or not uuid_:
        raise AuthException(
            "Minecraft profile incomplete (missing name/id).",
            code="MC-PROFILE-INCOMPLETE",
        )

    return {
        "access_token": mc_access_token,
        "username": username,
        "uuid": uuid_,
        "refresh_token": token_data.get("refresh_token", ""),
    }
