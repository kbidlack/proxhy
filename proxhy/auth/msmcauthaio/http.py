import asyncio
from typing import Dict, Optional, Union

import aiohttp

from .constants import BASE_HEADERS


class Http:
    """An http Client to handle requests."""

    def __init__(self, *, loop: asyncio.AbstractEventLoop = None):
        self.loop = loop or asyncio.get_event_loop()
        self.session = aiohttp.ClientSession(loop=self.loop)
        self.loop.set_exception_handler(lambda _loop, _context: None)

    async def close(self):
        """Close the HTTP session."""
        await self.session.close()

    async def request(
        self, url: str, method: str = "GET", **kwargs
    ) -> Union[aiohttp.ClientResponse, Union[Dict[str, str], str]]:
        """Handling requests.

        Parameters
        ----------
        url : :class:`str`
            Url to send request.
        method : :class:`str`
            Request method. Default: GET

        Returns
        ----------
        data : :class:`Union[:class:`aiohttp.ClientResponse`, :class:`Union`]`
            Request returned data.
        """
        headers = {**BASE_HEADERS, **(kwargs.pop("headers", {}))}

        async with self.session.request(method, url, headers=headers, **kwargs) as res:
            try:
                return res, await res.json()
            except:
                return res, await res.text()
