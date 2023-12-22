from .helpers import Microsoft, Xbox
from .client import MsMcAuth
from .http import Http

from .models import (
    XSTSAuthenticateResponse,
    XblAuthenticateResponse,
    UserLoginResponse,
    PreAuthResponse,
    UserProfile
)

from .errors import (
    XstsAuthenticationFailed,
    XblAuthenticationFailed,
    LoginWithXboxFailed,
    InvalidCredentials,
    MsMcAuthException,
    TwoFactorAccount,
    NoXboxAccount,
    ChildAccount,
    NotPremium
)