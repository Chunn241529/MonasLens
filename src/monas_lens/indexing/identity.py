"""Deterministic structural identifiers."""

from hashlib import sha256


def stable_id(*parts: object) -> str:
    digest = sha256()
    for part in parts:
        encoded = str(part).encode("utf-8")
        digest.update(len(encoded).to_bytes(4, "big"))
        digest.update(encoded)
    return digest.hexdigest()
