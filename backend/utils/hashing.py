"""Hashing and fingerprinting utilities."""

import hashlib
from pathlib import Path
from typing import BinaryIO


def hash_file(file_path: str | Path, algorithm: str = "sha256") -> str:
    """Calculate hash of a file.

    Args:
        file_path: Path to file
        algorithm: Hash algorithm (sha256, md5, sha1)

    Returns:
        Hex digest of file hash
    """
    hasher = hashlib.new(algorithm)

    with open(file_path, "rb") as f:
        # Read in chunks for memory efficiency
        for chunk in iter(lambda: f.read(8192), b""):
            hasher.update(chunk)

    return hasher.hexdigest()


def hash_file_stream(file_stream: BinaryIO, algorithm: str = "sha256") -> str:
    """Calculate hash of a file stream.

    Args:
        file_stream: File-like object
        algorithm: Hash algorithm

    Returns:
        Hex digest of content hash
    """
    hasher = hashlib.new(algorithm)

    # Read in chunks
    for chunk in iter(lambda: file_stream.read(8192), b""):
        hasher.update(chunk)

    # Reset stream position
    file_stream.seek(0)

    return hasher.hexdigest()


def hash_text(text: str, algorithm: str = "sha256") -> str:
    """Calculate hash of text content.

    Args:
        text: Text to hash
        algorithm: Hash algorithm

    Returns:
        Hex digest
    """
    hasher = hashlib.new(algorithm)
    hasher.update(text.encode("utf-8"))
    return hasher.hexdigest()


def hash_dict(data: dict, algorithm: str = "sha256") -> str:
    """Calculate deterministic hash of a dictionary.

    Sorts keys for deterministic ordering.

    Args:
        data: Dictionary to hash
        algorithm: Hash algorithm

    Returns:
        Hex digest
    """
    import json

    # Sort keys for deterministic ordering
    serialized = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return hash_text(serialized, algorithm)


def content_fingerprint(content: str) -> str:
    """Generate a short fingerprint for content deduplication.

    Returns first 16 characters of SHA-256 hash.
    """
    return hash_text(content)[:16]


def chunk_fingerprint(
    content: str,
    metadata: dict | None = None,
) -> str:
    """Generate fingerprint for a document chunk.

    Combines content hash with metadata for uniqueness.
    """
    hasher = hashlib.sha256()
    hasher.update(content.encode("utf-8"))

    if metadata:
        # Add relevant metadata fields
        for key in sorted(metadata.keys()):
            value = metadata[key]
            if isinstance(value, (str, int, float, bool)):
                hasher.update(f"{key}:{value}".encode("utf-8"))

    return hasher.hexdigest()[:24]


def generate_cache_key(*args, **kwargs) -> str:
    """Generate a cache key from arguments.

    Useful for memoization and caching.
    """
    import json

    key_parts = [str(arg) for arg in args]
    if kwargs:
        key_parts.append(json.dumps(kwargs, sort_keys=True))

    combined = ":".join(key_parts)
    return hash_text(combined)[:32]


def verify_file_hash(
    file_path: str | Path,
    expected_hash: str,
    algorithm: str = "sha256",
) -> bool:
    """Verify file matches expected hash.

    Args:
        file_path: Path to file
        expected_hash: Expected hash value
        algorithm: Hash algorithm used

    Returns:
        True if hashes match
    """
    actual_hash = hash_file(file_path, algorithm)
    return actual_hash.lower() == expected_hash.lower()


def short_hash(text: str, length: int = 8) -> str:
    """Generate a short hash for display purposes.

    Args:
        text: Text to hash
        length: Desired hash length (max 64)

    Returns:
        Truncated hex digest
    """
    return hash_text(text)[:min(length, 64)]
