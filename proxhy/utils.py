import asyncio
from typing import Optional

from hypixel import Client
from hypixel.client import JSON_DECODER
from hypixel.errors import (
    ApiError,
    ClosedSession,
    InvalidApiKey,
    KeyRequired,
    RateLimitError,
)
from hypixel.utils import HashedDict


class APIClient(Client):
    BASE_API_URL = "https://hypixel-api.mckingkb.workers.dev/iris"

    # https://github.com/duhby/hypixel.py/blob/master/hypixel/client.py#L403
    async def _get(
        self,
        path: str,
        *,
        # Hashed to allow caching
        params: Optional[HashedDict] = None,
        **_,
    ) -> dict:
        """Retrieves raw data from hypixel.

        Parameters
        ----------
        path: str
            The API path to request from.
        params: Optional[:class:`~utils.HashedDict`]
            Parameters to give the API.

        Raises
        ------
        ApiError
            An unexpected error occurred with the Hypixel API.
        ClosedSession
            ``self.ClientSession`` is closed.
        InvalidApiKey
            The API key used is invalid.
        KeyRequired
            No keys were passed into the client or the method and
            ``key_required`` is ``True``.
        RateLimitError
            The rate limit is exceeded and ``self.rate_limit_m`` is
            ``False``.

        Returns
        -------
        :class:`dict`
            The Hypixel API response.
        """

        if self._session.closed:
            raise ClosedSession
        if params is None:
            params = {}
        params = dict(params)  # Allow mutations

        try:
            response = await self._session.get(
                f"{self.BASE_API_URL}/{path}", params=params
            )
        except asyncio.TimeoutError:
            raise TimeoutError("hypixel")

        if response.status == 429:
            if not self.rate_limit_h:
                # Initially <class 'str'>
                retry_after = int(response.headers["Retry-After"])
                raise RateLimitError(retry_after, "hypixel", response)
            else:
                while response.status == 429:
                    # Retrying exactly after the amount of seconds can
                    # cause spamming the API while still being limited
                    # because the time is restricted to int precision.
                    retry = int(response.headers["Retry-After"]) + 1
                    if self.timeout is not None and retry > self.timeout:
                        raise TimeoutError("hypixel")
                    await asyncio.sleep(retry)
                    response = await self._get_helper(path, params)

        if response.status == 200:
            return await response.json(loads=JSON_DECODER)

        elif response.status == 403:
            if params.get("key") is None:
                raise KeyRequired(path)
            raise InvalidApiKey(params["key"])

        else:
            try:
                text = await response.json(loads=JSON_DECODER)
                text = text.get("cause")
            except Exception:
                raise ApiError(response, "hypixel")
            else:
                text = f"An unexpected error occurred with the hypixel API: {text}"
                raise ApiError(response, "hypixel", text)
