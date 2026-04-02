"""Custom exceptions for the Pragma Market SDK."""


class PragmaError(Exception):
    """Base error for SDK failures."""


class PragmaConfigError(PragmaError):
    """Raised when local wallet or config state is missing or invalid."""


class PragmaNotRegisteredError(PragmaConfigError):
    """Raised when an agent-only command is used before registration."""


class PragmaAPIError(PragmaError):
    """Raised when the Pragma API returns an error."""

    def __init__(self, message, *, status_code=None, payload=None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


class PragmaAuthError(PragmaAPIError):
    """Raised when signed authentication fails."""


class PragmaValidationError(PragmaError):
    """Raised when command or SDK inputs are invalid."""


class PragmaOutdatedError(PragmaError):
    """Raised when the installed SDK is too far behind the minimum supported version."""
