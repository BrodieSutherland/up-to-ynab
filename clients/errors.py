class UpstreamError(Exception):
    """An Up or YNAB call failed: transport, non-success status, or bad payload.

    The message names the method, path and status or exception class. It never
    carries headers or tokens.
    """

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code
