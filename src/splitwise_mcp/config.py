import os
from dataclasses import dataclass, field
from pathlib import Path

from .errors import AppError


@dataclass(frozen=True)
class Settings:
    owner: str
    account_id: int
    api_key: str = field(repr=False)
    database: str = field(repr=False)
    remote: bool = False
    caller_token_hash: str = field(default="", repr=False)
    host: str = ""
    writes: bool = False
    approval_public_key: str = ""
    fixture: bool = False
    port: int = 8000

    def validate(self):
        if not self.owner or len(self.owner) > 100 or self.account_id <= 0 or not self.api_key:
            raise AppError("configuration", "Set SW_OWNER, SW_ACCOUNT_ID, and SW_API_KEY securely.")
        if not self.database or (self.remote and not self.database.startswith("postgresql://")):
            raise AppError(
                "configuration", "Remote mode requires explicitly configured durable PostgreSQL."
            )
        if self.remote:
            import re
            from urllib.parse import parse_qs, urlparse

            if parse_qs(urlparse(self.database).query).get("sslmode") != ["verify-full"]:
                raise AppError(
                    "configuration",
                    "Remote PostgreSQL requires sslmode=verify-full and a trusted CA.",
                )

            if (
                self.fixture
                or not re.fullmatch(r"[0-9a-f]{64}", self.caller_token_hash)
                or not re.fullmatch(r"[a-zA-Z0-9.-]+(?::[0-9]{1,5})?", self.host)
            ):
                raise AppError(
                    "configuration",
                    "Remote mode requires an exact allowed host and a dedicated SHA256 caller token hash; fixtures are local-only.",
                )
        if self.writes and (not self.approval_public_key or self.fixture):
            raise AppError(
                "configuration",
                "Live writes require an external human approval public key; fixture mode never enables live writes.",
            )
        if not 1 <= self.port <= 65535:
            raise AppError("configuration", "Invalid PORT.")
        return self

    @classmethod
    def from_env(cls):
        try:
            result = cls(
                owner=os.getenv("SW_OWNER", ""),
                account_id=int(os.getenv("SW_ACCOUNT_ID", "0")),
                api_key=os.getenv("SW_API_KEY", ""),
                database=os.getenv(
                    "SW_DATABASE", str(Path.home() / ".local/share/splitwise-mcp/state.sqlite")
                ),
                remote=os.getenv("SW_REMOTE", "false") == "true",
                caller_token_hash=os.getenv("SW_CALLER_TOKEN_SHA256", ""),
                host=os.getenv("SW_ALLOWED_HOST", ""),
                writes=os.getenv("SW_ENABLE_WRITES", "false") == "true",
                approval_public_key=os.getenv("SW_APPROVAL_PUBLIC_KEY", ""),
                fixture=os.getenv("SW_FIXTURE", "false") == "true",
                port=int(os.getenv("PORT", "8000")),
            )
        except ValueError:
            raise AppError("configuration", "Invalid numeric configuration.") from None
        return result.validate()
