from urllib.parse import quote_plus
from typing import Optional
from re import search

from ..http import Http
from ..constants import AUTHORIZE
from ..models import PreAuthResponse, UserLoginResponse
from ..errors import InvalidCredentials, TwoFactorAccount, MsMcAuthException

__all__ = ("Xbox",)

class Xbox:
    """"Xbox requests handler.

    Attributes
    ----------
    http : Optional[:class:`Http`]
        Http client.
    """

    def __init__(self, http: Optional[Http] = None):
        self.http = http

    async def get_pre_auth(self) -> PreAuthResponse:
        _, text = await self.http.request(AUTHORIZE, allow_redirects=True)

        sft_tag = search(r"sFTTag:'(.*?)'", text).group(1)
        flow_token = search(r"value=\"(.*?)\"", sft_tag).group(1)
        post_url = search(r"urlPost:'(.+?(?=\'))", text).group(1)

        if (flow_token or post_url) is None:
            raise MsMcAuthException("Couldn't extract sFTTag and urlPost")

        return PreAuthResponse(flow_token=flow_token, post_url=post_url)

    async def xbox_login(self, email: str, password: str, pre_auth: PreAuthResponse) -> UserLoginResponse:
        """Check user credentials.

        Parameters
        ----------
        email : :class:`str`
            Email to log into.
        password : :class:`str`
            Password of the email to log into.
        pre_auth : :class:`PreAuthResponse`
            Pre auth response.
        Returns
        -------
        user : :class:`UserLoginResponse`
            User login response.
        """

        data = f"login={self.encode(email)}&loginfmt={self.encode(email)}" \
               f"&passwd={self.encode(password)}&PPFT={self.encode(pre_auth.flow_token)}"

        res, text = await self.http.request(
            pre_auth.post_url,
            "POST", data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            allow_redirects=True
        )

        if "access_token" not in str(res.real_url) or str(res.real_url) == pre_auth.post_url:
            if "Sign in to" in str(text):
                raise InvalidCredentials("Provided credentials was invalid.")
            elif "Help us protect your account" in str(text):
                raise TwoFactorAccount("2FA is enabled but not supported yet.")
            else:
                raise MsMcAuthException(f"Something went wrong. Status Code: {res.status}")

        data = str(res.real_url).split("#")[1].split("&")
        return UserLoginResponse(
            refresh_token=data[4].split("=")[1],
            access_token=data[0].split("=")[1],
            expires_in=int(data[2].split("=")[1]),
            logged_in=True
        )

    def encode(self, data: str) -> str:
        """Encodes data."""
        return quote_plus(data)