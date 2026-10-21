"""Signed update verification (REQ-SEC-003, TASK-034).

An update manifest is JSON ``{"version", "files": {name: sha256}}`` signed with
Ed25519. :func:`verify_update` checks the signature against a pinned public key
*before* touching any file, then checks every file's SHA-256 and rejects
unlisted or missing files and path traversal. It never installs anything; the
caller installs only if it returns without raising.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from ..domain.errors import ValidationError


def _canonical(manifest: dict) -> bytes:
    return json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()


def sign_manifest(manifest: dict, private_key: Ed25519PrivateKey) -> bytes:
    return private_key.sign(_canonical(manifest))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _version_tuple(v: str) -> tuple[int, ...]:
    try:
        return tuple(int(p) for p in v.split("."))
    except ValueError as exc:
        raise ValidationError(f"invalid version {v!r}") from exc


def verify_update(manifest: dict, signature: bytes, public_key: bytes, directory: Path, *,
                  current_version: str) -> None:
    """Raise ValidationError unless the update is authentic, intact and newer."""
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(signature, _canonical(manifest))
    except (InvalidSignature, ValueError) as exc:
        raise ValidationError("update signature invalid") from exc
    if _version_tuple(manifest.get("version", "")) <= _version_tuple(current_version):
        raise ValidationError("update is not newer than the installed version (downgrade refused)")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise ValidationError("manifest lists no files")
    root = directory.resolve()
    present = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    if present != set(files):
        raise ValidationError(f"file set differs from manifest: {sorted(present ^ set(files))}")
    for name, digest in files.items():
        p = (root / name).resolve()
        if root not in p.parents:
            raise ValidationError(f"path escapes update directory: {name}")
        if sha256_file(p) != digest:
            raise ValidationError(f"checksum mismatch: {name}")
