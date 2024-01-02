"""patched version of msmcauthaio that works on os' other than windows w/helper funcs"""

import getpass
import time

from keyring import get_password, set_password

from .msmcauthaio import MsMcAuth, UserProfile


# https://pypi.org/project/msmcauthaio/
async def load_auth_info() -> UserProfile:
    email = get_password("proxhy", "email")
    password = get_password("proxhy", "password")
    username = get_password("proxhy", "username")
    uuid = get_password("proxhy", "uuid")
    access_token = get_password("proxhy", "access_token")
    access_token_gen_time = get_password("proxhy", "access_token_gen_time") or 0.0

    if not (email and password):
        email = input("Enter your Microsoft login email: ").strip()
        password = getpass.getpass("Enter your Microsoft login password: ").strip()
        set_password("proxhy", "email", email)
        set_password("proxhy", "password", password)

        print("Generating credentials...", end="", flush=True)
        user_profile = await MsMcAuth().login(email, password)
        access_token_gen_time = time.time()
        print("done!")
    elif time.time() - float(access_token_gen_time) > 86000.0:
        print("Regenerating credentials...", end="", flush=True)
        user_profile = await MsMcAuth().login(email, password)
        access_token_gen_time = time.time()
        print("done!")
    else:
        user_profile = UserProfile(
            access_token=access_token, username=username, uuid=uuid
        )

    set_password("proxhy", "email", email)
    set_password("proxhy", "password", password)
    set_password("proxhy", "username", user_profile.username)
    set_password("proxhy", "uuid", user_profile.uuid)
    set_password("proxhy", "access_token", access_token)
    set_password("proxhy", "access_token_gen_time", str(access_token_gen_time))

    return user_profile
