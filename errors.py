"""Error types shared by both mail backends (Microsoft 365 / Graph and classic Outlook / COM).

Each error carries a friendly message, an HTTP status and a stable `code` the frontend understands.
"""


class OutlookError(Exception):
    status = 500
    code = "mail_error"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


MailError = OutlookError


class BadRequest(OutlookError):
    status = 400
    code = "bad_request"


class NotSignedIn(OutlookError):
    status = 401
    code = "not_signed_in"


class OutlookPermissionDenied(OutlookError):
    status = 403
    code = "permission_denied"


class ConsentRequired(OutlookError):
    status = 403
    code = "consent_required"


class NotFound(OutlookError):
    status = 404
    code = "not_found"


class RateLimited(OutlookError):
    status = 429
    code = "rate_limited"


class ServiceUnavailable(OutlookError):
    status = 503
    code = "service_unavailable"


# Classic Outlook (COM) specific
class OutlookNotRunning(OutlookError):
    status = 503
    code = "outlook_not_running"


class OutlookNotInstalled(OutlookError):
    status = 503
    code = "outlook_not_installed"


class OutlookBusy(OutlookError):
    status = 503
    code = "outlook_busy"
