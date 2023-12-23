"""patched version of msmcauthaio that works on os' other than windows w/helper funcs"""
import getpass
import json
import time
from pathlib import Path
from typing import Any, Coroutine

from appdirs import user_cache_dir

from .msmcauthaio import MsMcAuth, UserProfile


# https://pypi.org/project/msmcauthaio/
async def load_auth_info() -> Coroutine[Any, Any, tuple]:
    msmcauth = MsMcAuth()

    (cache_dir := Path(user_cache_dir("proxhy"))).mkdir(parents=True, exist_ok=True)
    auth_cache_path = cache_dir / Path("auth.json")
    if auth_cache_path.exists():
        with open(auth_cache_path, "r") as auth_cache_file:
            auth_data = json.load(auth_cache_file)

        # tokens expire after 86400 seconds so give a little space
        if time.monotonic() - float(auth_data["access_token_gen_time"]) > 86200.0:
            print("Regenerating credentials...", end="", flush=True)
            user_profile = await msmcauth.login(email, password)
            print("done!")
        else:
            user_profile = UserProfile(
                auth_data["access_token"], auth_data["username"], auth_data["uuid"]
            )
    else:
        email = input("Enter your Microsoft login email: ").strip()
        password = getpass.getpass("Enter your Microsoft login password: ")
        print("Generating credentials...", end="", flush=True)
        user_profile = await msmcauth.login(email, password)
        print("done!")

    auth_data = {
        "access_token": user_profile[0],
        "access_token_gen_time": str(time.monotonic()),
        "username": user_profile[1],
        "uuid": user_profile[2],
    }
    with open(auth_cache_path, "w") as auth_cache_file:
        json.dump(auth_data, auth_cache_file)

    return auth_data["access_token"], auth_data["uuid"], auth_data["username"]


async def load_loop():
    load_auth_info
