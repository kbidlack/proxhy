import asyncio
from typing import Optional

from .errors import NotPremium
from .helpers import Microsoft, Xbox
from .http import Http
from .models import UserProfile


class MsMcAuth:
    """Microsoft Minecraft Auth Client."""

    def __init__(self, *, loop: asyncio.AbstractEventLoop = None):
        self.http = Http(loop=loop or asyncio.get_event_loop())

    async def login(self, email: str, password: str) -> UserProfile:
        xbox = Xbox(http=self.http)
        microsoft = Microsoft(http=self.http)

        _login = await xbox.xbox_login(email, password, (await xbox.get_pre_auth()))

        xbl = await microsoft.handle_xbl(_login)
        xsts = await microsoft.handle_xsts(xbl)

        access_token = await microsoft.login_with_xbox(xsts)
        has_the_game = await microsoft.user_hash_game(access_token)

        if has_the_game:
            return await microsoft.get_minecraft_profile(access_token)

        raise NotPremium("Account is not premium.")
