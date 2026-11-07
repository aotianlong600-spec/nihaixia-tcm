"""Transport-free domain failures shared by desktop and portable core."""


class DomainError(Exception):
    """A business failure carrying the HTTP status the desktop edge should use."""

    def __init__(self, status_code, detail):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
