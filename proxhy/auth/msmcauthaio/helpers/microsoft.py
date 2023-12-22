from typing import Optional

from ..constants import LOGIN_WITH_XBOX, XBL, XSTS, OWNERSHIP, PROFILE
from ..http import Http

from ..models import (
    XSTSAuthenticateResponse,
    XblAuthenticateResponse,
    UserLoginResponse,
    PreAuthResponse,
    UserProfile
)

from ..errors import (
    XstsAuthenticationFailed,
    XblAuthenticationFailed,
    LoginWithXboxFailed,
    MsMcAuthException,
    NoXboxAccount,
    ChildAccount,
)

__all__ = ("Microsoft",)

class Microsoft:
    """"Microsoft requests handler.

    Attributes
    ----------
    http : Optional[:class:`Http`]
        Http client.
    """

    def __init__(self, http: Optional[Http] = None):
        self.http = http

    async def handle_xbl(self, response: UserLoginResponse) -> XblAuthenticateResponse:
        """Handle xbl authenticate.

        Parameters
        ----------
        response : :class:`UserLoginResponse`
            Xbox login response.
        Returns
        ----------
        data : :class:`XblAuthenticateResponse`
            Xbl data.
        """

        payload = {
            "RelyingParty": "http://auth.xboxlive.com",
            "TokenType": "JWT",
            "Properties": {
                "AuthMethod": "RPS",
                "SiteName": "user.auth.xboxlive.com",
                "RpsTicket": response.access_token,
            }
        }

        res, text = await self.http.request(
            XBL, "POST",
            json=payload,
            headers={"Accept": "application/json", "x-xbl-contract-version": "0"}
        )

        if res.status != 200:
            raise XblAuthenticationFailed(f"Xbl Authentication failed. Status code: {res.status}")

        data = await res.json()
        return XblAuthenticateResponse(
            token=data["Token"],
            user_hash=data["DisplayClaims"]["xui"][0]["uhs"]
        )

    async def handle_xsts(self, response: XblAuthenticateResponse) -> XSTSAuthenticateResponse:
        """Handle xsts authenticate.

        Parameters
        ----------
        response : :class:`XblAuthenticateResponse`
            Xbl login response.
        Returns
        ----------
        data : :class:`XSTSAuthenticateResponse`
            Xsts data.
        """

        payload = {
            "RelyingParty": "rp://api.minecraftservices.com/",
            "TokenType": "JWT",
            "Properties": {
                "SandboxId": "RETAIL",
                "UserTokens": [
                    response.token
                ]
            }
        }

        res, text = await self.http.request(
            XSTS, "POST",
            json=payload,
            headers={"Accept": "application/json", "x-xbl-contract-version": "0"}
        )

        if res.status != 200:
            if res.status == 401:
                json = await res.json()
                if json["XErr"] == "2148916233":
                    raise NoXboxAccount("This account doesn't have an Xbox account.")
                elif json["XErr"] == "2148916238":
                    raise ChildAccount("The account is a child account, Under 18.")
                else:
                    raise Exception(f"Unknown Xsts. Error code: {json['XErr']}")
            else:
                raise XstsAuthenticationFailed("Xsts Authentication failed.")

        data = await res.json()
        return XSTSAuthenticateResponse(
            token=data["Token"],
            user_hash=data["DisplayClaims"]["xui"][0]["uhs"]
        )

    async def login_with_xbox(self, response: XSTSAuthenticateResponse) -> str:
        """Handle xbox login.

        Parameters
        ----------
        response : :class:`XSTSAuthenticateResponse`
            Xsts login response.
        Returns
        ----------
        data : :class:`str`
            Access token.
        """

        res, text = await self.http.request(
            LOGIN_WITH_XBOX, "POST",
            json={"identityToken": f"XBL3.0 x={response.user_hash};{response.token}"},
            headers={"Accept": "application/json"}
        )

        if "access_token" not in str(text):
            raise LoginWithXboxFailed("Logging with xbox failed.")

        return (await res.json())["access_token"]

    async def user_hash_game(self, access_token: str) -> bool:
        """Check if user has Minecraft.

        Parameters
        ----------
        access_token : :class:`str`
            Access token.
        Returns
        ----------
        data : :class:`bool`
            User has the game.
        """

        res, text = await self.http.request(
            OWNERSHIP,
            headers={"Accept": "application/json", "Authorization": f"Bearer {access_token}"}
        )

        return len((await res.json())["items"]) > 0

    async def get_minecraft_profile(self, access_token: str) -> UserProfile:
        """Get minecraft profile info.

        Parameters
        ----------
        access_token : :class:`str`
            Access token.
        Returns
        ----------
        data : :class:`UserProfile`
            Minecraft user profile.
        """

        res, text = await self.http.request(
            PROFILE,
            headers={"Accept": "application/json", "Authorization": f"Bearer {access_token}"}
        )

        data = (await res.json())
        return UserProfile(
            access_token=access_token,
            username=data.get("name"),
            uuid=data.get("id"),

            is_demo=(data.get("name") is None)
        )