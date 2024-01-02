"""patched version of msmcauthaio that works on os' other than windows w/helper funcs"""

import ast
import base64
import getpass
import time
from pathlib import Path

from appdirs import user_cache_dir

from .msmcauthaio import MsMcAuth, UserProfile


# https://pypi.org/project/msmcauthaio/
async def load_auth_info() -> tuple[str]:
    # oh my god this is so stupid lmao
    (cache_dir := Path(user_cache_dir("proxhy"))).mkdir(parents=True, exist_ok=True)
    auth_cache_path = cache_dir / Path("auth")
    if auth_cache_path.exists():
        with open(auth_cache_path, "rb") as file:
            auth_data = file.read()
    else:
        auth_data = base64.b64encode(str(tuple("" for _ in range(7))).encode("utf-8"))

    (
        email,
        password,
        username,
        uuid,
        access_token,
        access_token_gen_time,
        api_key,
    ) = ast.literal_eval(base64.b64decode(auth_data).decode("utf-8"))

    if not (email and password):
        email = input("Enter your Microsoft login email: ").strip()
        password = getpass.getpass("Enter your Microsoft login password: ").strip()
        api_key = input("Enter your Hypixel API Key: ")

        print("Generating credentials...", end="", flush=True)
        user_profile = await MsMcAuth().login(email, password)
        access_token_gen_time = str(time.time())
        print("done!")
    elif time.time() - float(access_token_gen_time) > 86000.0:
        print("Regenerating credentials...", end="", flush=True)
        user_profile = await MsMcAuth().login(email, password)
        access_token_gen_time = str(time.time())
        print("done!")
    else:
        user_profile = UserProfile(access_token, username, uuid)

    with open(auth_cache_path, "wb") as file:
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
                        api_key,
                    )
                ).encode("utf-8")
            )
        )

    return user_profile.access_token, user_profile.username, user_profile.uuid, api_key
