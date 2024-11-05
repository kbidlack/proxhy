#
#
#
#
#
# THIS DOESN WORK LOL
#
#
#
#
#
#
#


import re
from urllib.parse import unquote

import requests

# Constants
LOGIN_URL = "https://login.live.com/oauth20_authorize.srf?client_id=000000004C12AE6F&redirect_uri=https://login.live.com/oauth20_desktop.srf&scope=service::user.auth.xboxlive.com::MBI_SSL&display=touch&response_type=token&locale=en"
XBOX_LIVE_AUTH_URL = "https://user.auth.xboxlive.com/user/authenticate"
XSTS_AUTH_URL = "https://xsts.auth.xboxlive.com/xsts/authorize"
MINECRAFT_AUTH_URL = "https://api.minecraftservices.com/authentication/login_with_xbox"


# Function to extract sFTTag and urlPost values
def get_auth_params():
    session = requests.Session()
    response = session.get(LOGIN_URL)
    sfttag = re.search(r'value="(.+?)"', response.text).group(1)
    url_post = re.search(r"urlPost:'(.+?)'", response.text).group(1)
    return session, sfttag, url_post


# Function to perform the Microsoft login
def microsoft_login(email, password, sfttag, url_post, session):
    login_data = {"login": email, "loginfmt": email, "passwd": password, "PPFT": sfttag}
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    response = session.post(
        url_post, data=login_data, headers=headers, allow_redirects=True
    )
    # Check if login failed (no access token in URL)
    if "access_token" not in response.url:
        raise ValueError(
            "Login failed. Check credentials or if two-factor authentication is enabled."
        )
    return response.url


# Extract tokens from the final redirected URL
def extract_tokens(url):
    raw_data = url.split("#")[1]
    token_data = dict(item.split("=") for item in raw_data.split("&"))
    token_data["access_token"] = unquote(token_data["access_token"])
    token_data["refresh_token"] = unquote(token_data["refresh_token"])
    return token_data


# Function to authenticate with Xbox Live
def xbox_live_auth(access_token):
    payload = {
        "Properties": {
            "AuthMethod": "RPS",
            "SiteName": "user.auth.xboxlive.com",
            "RpsTicket": access_token,
        },
        "RelyingParty": "http://auth.xboxlive.com",
        "TokenType": "JWT",
    }
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    response = requests.post(XBOX_LIVE_AUTH_URL, json=payload, headers=headers)
    response_data = response.json()
    return response_data["Token"], response_data["DisplayClaims"]["xui"][0]["uhs"]


# Function to get the XSTS token
def get_xsts_token(xbox_token):
    payload = {
        "Properties": {"SandboxId": "RETAIL", "UserTokens": [xbox_token]},
        "RelyingParty": "rp://api.minecraftservices.com/",
        "TokenType": "JWT",
    }
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    response = requests.post(XSTS_AUTH_URL, json=payload, headers=headers)
    response_data = response.json()
    return response_data["Token"], response_data["DisplayClaims"]["xui"][0]["uhs"]


# Function to get the Minecraft bearer token
def get_minecraft_token(xsts_token, user_hash):
    payload = {
        "identityToken": f"XBL3.0 x={user_hash};{xsts_token}",
        "ensureLegacyEnabled": True,
    }
    headers = {"Content-Type": "application/json"}
    response = requests.post(MINECRAFT_AUTH_URL, json=payload, headers=headers)
    response_data = response.json()
    return response_data["access_token"]


# Main login flow
def minecraft_login(email, password):
    # Step 1: Get initial auth parameters
    session, sfttag, url_post = get_auth_params()

    # Step 2: Microsoft login
    final_url = microsoft_login(email, password, sfttag, url_post, session)
    tokens = extract_tokens(final_url)

    # Step 3: Xbox Live authentication
    xbox_token, user_hash = xbox_live_auth(tokens["access_token"])

    # Step 4: Get XSTS token
    xsts_token, user_hash = get_xsts_token(xbox_token)

    # Step 5: Get Minecraft access token
    minecraft_token = get_minecraft_token(xsts_token, user_hash)

    print("Minecraft access token:", minecraft_token)
    return minecraft_token


# Usage example
email = "your_email_here"
password = "your_password_here"
try:
    minecraft_access_token = minecraft_login(email, password)
    print("Successfully logged in! Minecraft access token:", minecraft_access_token)
except Exception as e:
    print("An error occurred during login:", e)
