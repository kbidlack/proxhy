import time

import jwt
import keyring
import msmcauth


def login(email: str, password: str) -> tuple[str]:
    access_token, username, uuid = msmcauth.login(email, password)

    # save auth info
    keyring.set_password("proxhy", username, f"{access_token} {email} {uuid}")
    keyring.set_password("proxhy", email, password)

    return access_token, username, uuid


def user_exists(username: str) -> bool:
    return keyring.get_password("proxhy", username) is not None


# https://pypi.org/project/msmcauthaio/
def load_auth_info(username: str = "") -> tuple[str]:
    """should only be called with a cached username (check users() first)"""

    # scuffed ahh but it works
    access_token, email, uuid = keyring.get_password("proxhy", username).split(" ")
    password = keyring.get_password("proxhy", email)

    access_token_gen_time = jwt.decode(
        access_token, algorithms=["HS256"], options={"verify_signature": False}
    )["iat"]

    # ~24 hours
    if time.time() - float(access_token_gen_time) > 86000.0:
        access_token, username, uuid = login(email, password)

    return access_token, username, uuid


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
