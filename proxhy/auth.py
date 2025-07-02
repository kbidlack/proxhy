import time

import jwt
import keyring
import msmcauth


def login(email: str, password: str) -> tuple[str, str, str]:
    access_token, username, uuid = msmcauth.login(email, password)

    # save auth info
    safe_set("proxhy", username, f"{email} {uuid}")
    safe_set("proxhy", email, password)
    return access_token, username, uuid


def user_exists(username: str) -> bool:
    return keyring.get_password("proxhy", username) is not None


# https://pypi.org/project/msmcauthaio/
def load_auth_info(username: str = "") -> tuple[str, str, str]:
    record = keyring.get_password("proxhy", username)
    if record is None:
        raise RuntimeError(f"No cached credentials for user {username!r}")

    parts = record.split(" ")
    if len(parts) == 3:  # legacy entry with access_token
        access_token, email, uuid = parts

        # token fresh? (±24 h)
        iat = jwt.decode(
            access_token, algorithms=["HS256"], options={"verify_signature": False}
        )["iat"]
        if time.time() - float(iat) > 86_000:
            access_token, _, _ = login(
                email, keyring.get_password("proxhy", email) or ""
            )
        return access_token, username, uuid

    # new lightweight entry ─ always refresh
    email, uuid = parts
    password = keyring.get_password("proxhy", email) or ""
    access_token, _, _ = login(email, password)
    return access_token, username, uuid


# ---------- CRED-SIZE GUARD ----------
MAX_SECRET_CHARS = 1_250  # ≈2 500 bytes in the Windows vault


def safe_set(service: str, user: str, secret: str) -> None:
    """
    Write to the keyring unless the secret is too large for Windows
    Credential Manager's 2 560-byte blob limit.  Raises ValueError
    early instead of letting win32cred.CredWrite explode later.
    """
    if len(secret) > MAX_SECRET_CHARS:
        raise ValueError(
            f"Secret for {service}/{user} is too large "
            f"({len(secret)} > {MAX_SECRET_CHARS} characters)."
        )
    keyring.set_password(service, user, secret)


# -------------------------------------


def refresh_access_token(refresh_token: str) -> str:
    # https://gist.github.com/dewycube/223d4e9b3cddde932fbbb7cfcfb96759 for refresh token
    # https://mojang-api-docs.gapple.pw/authentication/msa

    # this doesn't work ):

    # r = requests.post(
    #     "https://login.live.com/oauth20_token.srf",
    #     data={
    #         "scope": "service::user.auth.xboxlive.com::MBI_SSL",
    #         "client_id": "000000004c12ae6f",
    #         "grant_type": "refresh_token",
    #         "refresh_token": refresh_token,
    #     },
    # )
    # print(r.json())
    # return r.json()["access_token"], r.json()["refresh_token"]

    raise NotImplementedError(
        "fun fact (if you couldn't tell by the error type): this isn't implemented"
        f"also I should do something with refresh_token so my editor likes me: {refresh_token}"
    )
