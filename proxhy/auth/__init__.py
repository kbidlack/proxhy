"""patched version of msmcauthaio that works on os' other than windows w/helper funcs"""

import ast
import base64
import time
from pathlib import Path

from appdirs import user_cache_dir

from .msmcauthaio import MsMcAuth, UserProfile


def users() -> list[str]:
    (cache_dir := Path(user_cache_dir("proxhy"))).mkdir(parents=True, exist_ok=True)
    return [file.name[5:] for file in cache_dir.glob("auth_*")]


async def login(email: str, password: str) -> UserProfile:
    (cache_dir := Path(user_cache_dir("proxhy"))).mkdir(parents=True, exist_ok=True)
    user_profile = await MsMcAuth().login(email, password)
    access_token_gen_time = str(time.time())

    with open(cache_dir / Path(f"auth_{user_profile.username}"), "wb") as file:
        file.write(
            base64.b64encode(
                str(
                    (
                        email,
                        password,
                        user_profile.username,
                        user_profile.uuid,
                        user_profile.access_token,
                        access_token_gen_time,
                    )
                ).encode("utf-8")
            )
        )

    return user_profile.access_token, user_profile.username, user_profile.uuid


# https://pypi.org/project/msmcauthaio/
async def load_auth_info(username: str = "") -> tuple[str]:
    """should only be called with a cached username (check users() first)"""
    # oh my god this is so stupid lmao
    (cache_dir := Path(user_cache_dir("proxhy"))).mkdir(parents=True, exist_ok=True)
    auth_cache_path = cache_dir / Path(f"auth_{username}")
    with open(auth_cache_path, "rb") as file:
        auth_data = file.read()
    (
        email,
        password,
        username,
        uuid,
        access_token,
        access_token_gen_time,
    ) = ast.literal_eval(base64.b64decode(auth_data).decode("utf-8"))

    if time.time() - float(access_token_gen_time) > 86000.0:
        user_profile = await MsMcAuth().login(email, password)
        access_token_gen_time = str(time.time())
    else:
        user_profile = UserProfile(access_token, username, uuid)

    return user_profile.access_token, user_profile.username, user_profile.uuid
