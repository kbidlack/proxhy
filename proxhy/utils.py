import asyncio
from collections import namedtuple

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


class _Client(Client):
    # literally just adds a profile function
    # because i don't wnat to have to query twice
    # to get uuid & name
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
