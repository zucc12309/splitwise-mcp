"""Verify approvals from a separate human-controlled signer; never issue them."""

import base64
import json
import time
from typing import Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import ValidationError

from .errors import AppError
from .models import Strict


class Claims(Strict):
    version: Literal[1]
    owner: str
    account_id: int
    draft_id: str
    draft_hash: str
    operation: Literal["create_expense"]
    expires_at: int
    nonce: str


def decode(text: str) -> bytes:
    return base64.b64decode(text + "=" * (-len(text) % 4), altchars=b"-_", validate=True)


class ApprovalVerifier:
    def __init__(self, public_key: str):
        try:
            self.key = (
                Ed25519PublicKey.from_public_bytes(decode(public_key)) if public_key else None
            )
        except ValueError:
            raise AppError("configuration", "Invalid approval public key.") from None

    def verify(self, token: str, row: dict, owner: str, account_id: int) -> Claims:
        if self.key is None:
            raise AppError(
                "writes_disabled",
                "Configure a separate trusted human approval signer before enabling writes.",
            )
        try:
            encoded, signature = token.split(".")
            message = decode(encoded)
            self.key.verify(decode(signature), message)
            claims = Claims.model_validate(json.loads(message))
            now = int(time.time())
            if (
                claims.owner != owner
                or claims.account_id != account_id
                or claims.draft_id != row["id"]
                or claims.draft_hash != row["draft_hash"]
                or not now < claims.expires_at <= min(row["expires"], now + 900)
                or not 16 <= len(claims.nonce) <= 128
            ):
                raise ValueError
            return claims
        except (ValueError, TypeError, InvalidSignature, ValidationError):
            raise AppError(
                "invalid_approval",
                "Approval is invalid, expired, or not bound to this exact owner/account/draft.",
            ) from None
