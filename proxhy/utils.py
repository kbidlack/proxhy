import asyncio
import hashlib
import inspect
import operator
import uuid as _uuid
from collections import namedtuple
from datetime import datetime
from typing import Optional

from hypixel import (
    ApiError,
    ClosedSession,
    InvalidPlayerId,
    PlayerNotFound,
    RateLimitError,
    utils,
)
from hypixel.client import JSON_DECODER, Client

PlayerInfo = namedtuple("PlayerInfo", ("name", "uuid"))


class APIClient(Client):
    # literally just adds a profile function
    # because i don't wnat to have to query twice
    # to get uuid & name

    async def _get_skin_properties_helper(self, uuid: str):
        """Helper to fetch skin properties from Mojang session server."""
        uuid_no_hyphens = uuid.replace("-", "")
        return await self._session.get(
            f"https://sessionserver.mojang.com/session/minecraft/profile/{uuid_no_hyphens}?unsigned=false",
            timeout=self.timeout,
        )

    async def _get_skin_properties(self, uuid: str) -> list[dict]:
        """Internal method to fetch skin properties."""
        if self._session.closed:
            raise ClosedSession
        try:
            response = await self._get_skin_properties_helper(uuid)
        except asyncio.TimeoutError:
            raise TimeoutError("mojang")

        if response.status == 429:
            if not self.rate_limit_m:
                retry_after = None
                raise RateLimitError(retry_after, "mojang", response)
            else:
                while response.status == 429:
                    backoff = utils.ExponentialBackoff(self.timeout)
                    retry = backoff.delay()
                    await asyncio.sleep(retry)
                    response = await self._get_skin_properties_helper(uuid)

        if response.status == 200:
            data = await response.json(loads=JSON_DECODER)
            properties = data.get("properties", [])
            return [
                {
                    "name": prop.get("name", ""),
                    "value": prop.get("value", ""),
                    "signature": prop.get("signature"),
                }
                for prop in properties
            ]

        elif response.status == 404:
            return []

        else:
            raise ApiError(response, "mojang")

    async def get_skin_properties(self, uuid: str) -> list[dict]:
        """Returns the skin properties of a player from their UUID.

        |mojang|

        Parameters
        ----------
        uuid: :class:`str`
            The UUID of the player (with or without hyphens).

        Raises
        ------
        ApiError
            An unexpected error occurred with the Mojang API.
        ClosedSession
            ``self.ClientSession`` is closed.
        RateLimitError
            The rate limit is exceeded and ``self.rate_limit_m`` is
            ``False``.
        TimeoutError
            The request took longer than ``self.timeout``, or the retry
            delay time is longer than ``self.timeout``.

        Returns
        -------
        :class:`list[dict]`
            A list of property dicts with 'name', 'value', and optionally
            'signature' keys. Returns an empty list if player not found.
        """
        return await self._get_skin_properties(uuid)

    async def _get_profile(self, name: str) -> PlayerInfo:
        if self._session.closed:
            raise ClosedSession
        try:
            response = await self._get_uuid_helper(name)
        except asyncio.TimeoutError:
            raise TimeoutError("mojang")

        if response.status == 429:
            if not self.rate_limit_m:
                retry_after = None
                raise RateLimitError(retry_after, "mojang", response)
            else:
                while response.status == 429:
                    backoff = utils.ExponentialBackoff(self.timeout)
                    retry = backoff.delay()
                    await asyncio.sleep(retry)
                    response = await self._get_uuid_helper(name)

        if response.status == 200:
            data = await response.json(loads=JSON_DECODER)
            uuid = data.get("id")
            name = data.get("name")
            if not uuid or not name:
                raise PlayerNotFound(name)
            return PlayerInfo(uuid=uuid, name=name)

        elif response.status == 404:
            raise PlayerNotFound(name)

        else:
            raise ApiError(response, "mojang")

    async def get_profile(self, name: str) -> PlayerInfo:
        """Returns the profile of a player from their username.

        |mojang|

        Parameters
        ----------
        name: :class:`str`
            The username of the player.

        Raises
        ------
        ApiError
            An unexpected error occurred with the Mojang API.
        ClosedSession
            ``self.ClientSession`` is closed.
        InvalidPlayerId
            The passed player name is not a string.
        PlayerNotFound
            The passed player name does not exist.
        RateLimitError
            The rate limit is exceeded and ``self.rate_limit_m`` is
            ``False``.
        TimeoutError
            The request took longer than ``self.timeout``, or the retry
            delay time is longer than ``self.timeout``.

        Returns
        -------
        :class:`PlayerInfo`
            The profile (name, uuid) of the player.
        """
        if not isinstance(name, str):
            raise InvalidPlayerId(name)
        return await self._get_profile(name)


# https://github.com/duhby/hypixel.py/blob/84fa52731d38a5939da70cac8753c967d0b70e3f/hypixel/models/player/utils.py#L144
def safe_div(a: int | float, b: int | float) -> float:
    if not b:
        return float(a)
    else:
        return round(a / b, 2)


def offline_uuid(username: str) -> _uuid.UUID:
    digest = hashlib.md5(f"OfflinePlayer:{username}".encode()).digest()
    return _uuid.UUID(bytes=bytes(digest), version=3)


def uuid_version(value: str) -> Optional[int]:
    try:
        return _uuid.UUID(value).version
    except ValueError:
        return None


def current_ln() -> Optional[int]:
    f_back_f_lineno = operator.attrgetter("f_back.f_lineno")
    return f_back_f_lineno(inspect.currentframe())  # lmfao


def zero_pad_calver(ver: str):
    """Pad a Proxhy version (CalVer) with 0s; e.g. 2026.2.19 -> 2026.02.19)"""
    dv = datetime.strptime(ver, "%Y.%m.%d")
    return dv.strftime("%Y.%m.%d")
