from typing import NamedTuple

class UserLoginResponse(NamedTuple):
    refresh_token: str
    access_token: str
    expires_in: int
    logged_in: bool = False

class XblAuthenticateResponse(NamedTuple):
    user_hash: str
    token: str

class XSTSAuthenticateResponse(NamedTuple):
    user_hash: str
    token: str

class UserProfile(NamedTuple):
    access_token: str
    username: str
    uuid: str

    is_demo: bool = False

class PreAuthResponse(NamedTuple):
    flow_token: str
    post_url: str