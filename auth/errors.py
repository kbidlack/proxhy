
class AuthException(Exception):
    """Base class for auth-related errors.

    Attributes
    ----------
    code : str | None
        A short machine-friendly error code (e.g., "MSA-INTERACTIVE", "MSA-WRONG-PASSWORD").
    detail : str | None
        Optional extra detail (e.g., server response text).
    """
    def __init__(self, message: str = "", *, code: str | None = None, detail: str | None = None):
        super().__init__(message)
        self.code = code
        self.detail = detail

    def __str__(self) -> str:
        if self.code:
            return f"[{self.code}] {super().__str__()}"
        return super().__str__()


class InvalidCredentials(AuthException):
    """Raised for wrong password OR interactive challenges the password-only flow can't satisfy."""


class NotPremium(AuthException):
    """Raised when the account does not own Minecraft: Java Edition."""
