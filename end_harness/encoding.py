"""Strict JSON serialization shared by hashes and persisted records."""
import hashlib
import json
import os
from pathlib import Path


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def strict_loads(value: str | bytes):
    def invalid(number):
        raise ValueError(f"Non-finite JSON number: {number}")
    result = json.loads(value, object_pairs_hook=_pairs, parse_constant=invalid)
    canonical(result)  # Also reject overflowed floats and invalid Unicode.
    return result


def canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def diagnostic(exc: BaseException) -> dict:
    """Lossless ASCII diagnostic, never a replacement for artifact bytes."""
    return {"error_type": type(exc).__name__, "message": ascii(str(exc)),
            "message_encoding": "python_ascii_repr"}


def write_once(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        if path.read_bytes() != data:
            raise ValueError(f"Immutable file mismatch: {path}")
