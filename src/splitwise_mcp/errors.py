"""Stable, safe errors: never include external bodies or credentials."""


class AppError(Exception):
    def __init__(self, code: str, message: str = "Request could not be completed."):
        self.code = code
        self.message = message
        super().__init__(code)
