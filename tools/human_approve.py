#!/usr/bin/env python3
"""Run ONLY on an independent human-controlled device inaccessible to the MCP host.

This utility is deliberately not installed as an MCP tool or server command.
A TTY alone is not a trust boundary. Key isolation is mandatory.
"""

import argparse
import base64
import getpass
import hashlib
import json
import os
import secrets
import sys
import time
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def b64(value):
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def exclusive_file(path, content):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as output:
        output.write(content)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["keygen", "approve"])
    parser.add_argument("--key", required=True)
    parser.add_argument("--preview")
    parser.add_argument("--out", required=True)
    parser.add_argument("--owner")
    parser.add_argument("--account", type=int)
    args = parser.parse_args()
    if not sys.stdin.isatty():
        raise SystemExit("Use an interactive terminal on your independent signing device.")
    if args.command == "keygen":
        password = getpass.getpass("New private-key passphrase (at least 16 characters): ")
        if len(password) < 16 or getpass.getpass("Repeat passphrase: ") != password:
            raise SystemExit("Passphrases must match and have at least 16 characters.")
        key = Ed25519PrivateKey.generate()
        exclusive_file(
            args.key,
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.BestAvailableEncryption(password.encode()),
            ),
        )
        exclusive_file(args.out, b64(key.public_key().public_bytes_raw()).encode())
        print(
            "Encrypted private key and public key saved. Transfer ONLY the public key to the server."
        )
        return
    if not args.preview or not args.owner or not args.account:
        raise SystemExit("approve requires --preview, --owner and --account.")
    raw = Path(args.preview).read_bytes()
    if len(raw) > 256_000:
        raise SystemExit("Preview too large.")
    preview = json.loads(raw)
    if preview["owner"] != args.owner or preview["account"]["id"] != args.account:
        raise SystemExit("Owner/account mismatch.")
    draft = {k: preview[k] for k in ("account", "group", "proposal", "allocations", "warnings")}
    if hashlib.sha256(canonical(draft)).hexdigest() != preview["draft_hash"]:
        raise SystemExit("Preview hash mismatch.")
    expires = min(preview["expires_at"], int(time.time()) + 300)
    if expires <= time.time():
        raise SystemExit("Draft expired; obtain a fresh preview.")
    # JSON escaping prevents terminal escape injection from descriptions/names.
    print(json.dumps(preview, ensure_ascii=True, indent=2))
    confirm = input(
        "Review every participant, payer, share, currency, group and date. Type APPROVE plus the full draft ID: "
    )
    if confirm != "APPROVE " + preview["draft_id"]:
        raise SystemExit("Not approved.")
    password = getpass.getpass("Private-key passphrase: ")
    key = serialization.load_pem_private_key(Path(args.key).read_bytes(), password.encode())
    if not isinstance(key, Ed25519PrivateKey):
        raise SystemExit("Expected Ed25519 key.")
    claims = {
        "version": 1,
        "owner": args.owner,
        "account_id": args.account,
        "draft_id": preview["draft_id"],
        "draft_hash": preview["draft_hash"],
        "operation": "create_expense",
        "expires_at": expires,
        "nonce": secrets.token_urlsafe(24),
    }
    message = canonical(claims)
    exclusive_file(args.out, (b64(message) + "." + b64(key.sign(message))).encode())
    print(
        "Approval saved. It permits one exact draft for at most five minutes; it does not post anything."
    )


if __name__ == "__main__":
    main()
