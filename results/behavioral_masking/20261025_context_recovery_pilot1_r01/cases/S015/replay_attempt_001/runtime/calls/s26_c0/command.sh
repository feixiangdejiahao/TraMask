cat > bandit/core/cache.py <<'EOF'
#
# Copyright 2025
#
# SPDX-License-Identifier: Apache-2.0
"""Incremental analysis cache for Bandit.

This module provides a persistent on-disk cache used by Bandit's
``--incremental`` mode.  Results for unchanged files (and files whose
dependencies have not changed) are stored so that they can be returned on
subsequent runs without rescanning the file.
"""
import hashlib
import json
import logging
import os
import shutil
import time

LOG = logging.getLogger(__name__)

CACHE_FILENAME = "cache.json"
FORMAT_VERSION = 1


def _json_default(obj):
    """JSON serializer for objects not natively serializable."""
    if isinstance(obj, set):
        return sorted(obj)
    if isinstance(obj, bytes):
        return obj.decode("utf-8", "replace")
    return str(obj)


def cache_key_from_parts(**parts):
    """Build a stable cache key from analysis-affecting parts.

    :param parts: keyword arguments describing analysis options/profile
    :return: hex digest identifying the analysis configuration
    """
    data = json.dumps(
        parts, sort_keys=True, default=_json_default, separators=(",", ":")
    )
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def file_hash(path):
    """Return a SHA-256 hash of the file at ``path``."""
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def hash_bytes(data):
    """Return a SHA-256 hash of the given bytes."""
    return hashlib.sha256(data).hexdigest()


class BanditCache:
    """A persistent cache for incremental analysis."""

    def __init__(
        self,
        cache_dir,
        cache_key=None,
        expiry_days=30,
        size_limit=None,
    ):
        """Initialize the cache.

        :param cache_dir: Directory where cache data is stored
        :param cache_key: Key identifying the current analysis configuration
        :param expiry_days: Number of days before an entry expires; ``0``
            expires every entry
        :param size_limit: Optional maximum cache file size in bytes
        """
        self.cache_dir = os.path.abspath(cache_dir)
        self.cache_path = os.path.join(self.cache_dir, CACHE_FILENAME)
        self.cache_key = cache_key
        self.expiry_days = expiry_days
        self.size_limit = size_limit
        self.entries = {}
        self.dirty = False
        self._load()

    def _load(self):
        """Load cache from disk, validating integrity.

        Corrupted entries are discarded.  A cache file with an incompatible
        format version is ignored entirely.
        """
        self.entries = {}
        self.dirty = False
        if not os.path.exists(self.cache_path):
            return

        try:
            with open(self.cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("cache root is not a dictionary")
            if data.get("format_version") != FORMAT_VERSION:
                LOG.warning(
                    "Cache has incompatible format version, ignoring cache"
                )
                self.dirty = True
                return

            entries = data.get("entries")
            if not isinstance(entries, dict):
                raise ValueError("cache entries are not a dictionary")

            for path, entry in entries.items():
                if self._valid_entry(entry):
                    self.entries[path] = entry
                else:
                    LOG.debug("Discarding corrupted cache entry: %s", path)
                    self.dirty = True

        except (OSError, ValueError) as e:
            LOG.warning("Cache is corrupted and will be discarded: %s", e)
            self.entries = {}
            self.dirty = True

    @staticmethod
    def _valid_entry(entry):
        """Return True if an entry has the expected structure."""
        return (
            isinstance(entry, dict)
            and isinstance(entry.get("path"), str)
            and isinstance(entry.get("file_hash"), str)
            and isinstance(entry.get("issues"), list)
            and isinstance(entry.get("metrics"), dict)
            and isinstance(entry.get("cached_at"), (int, float))
            and isinstance(entry.get("cache_key"), str)
        )

    def get(self, path):
        """Return the cached entry for ``path`` or None."""
        return self.entries.get(path)

    def __contains__(self, path):
        return path in self.entries

    def store(self, path, entry):
        """Store (or replace) a cache entry for ``path``."""
        self.entries[path] = entry
        self.dirty = True

    def remove(self, path):
        """Remove the cache entry for ``path``."""
        if path in self.entries:
            del self.entries[path]
            self.dirty = True

    def clear(self):
        """Remove all cached entries."""
        self.entries = {}
        self.dirty = True

    def save(self):
        """Write the cache to disk, creating the directory if needed."""
        if not self.entries and not os.path.exists(self.cache_path):
            return False

        os.makedirs(self.cache_dir, exist_ok=True)
        data = {
            "format_version": FORMAT_VERSION,
            "cache_key": self.cache_key,
            "updated_at": time.time(),
            "entries": self.entries,
        }
        tmp_path = self.cache_path + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, sort_keys=True, indent=2)
            os.replace(tmp_path, self.cache_path)
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
        self.dirty = False
        self._enforce_size_limit()
        return True

    def _enforce_size_limit(self):
        """If the cache exceeds ``size_limit``, drop oldest entries."""
        if not self.size_limit:
            return
        if not os.path.exists(self.cache_path):
            return

        while self.entries and os.path.getsize(self.cache_path) > self.size_limit:
            oldest = min(
                self.entries,
                key=lambda p: self.entries[p].get("cached_at", 0),
            )
            del self.entries[oldest]
            self._write_cache_file()

    def _write_cache_file(self):
        """Write the current entries to disk."""
        os.makedirs(self.cache_dir, exist_ok=True)
        data = {
            "format_version": FORMAT_VERSION,
            "cache_key": self.cache_key,
            "updated_at": time.time(),
            "entries": self.entries,
        }
        tmp_path = self.cache_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, sort_keys=True, indent=2)
        os.replace(tmp_path, self.cache_path)
        self.dirty = False

    def list_files(self):
        """Return a sorted list of paths present in the cache."""
        return sorted(self.entries.keys())

    def prune(self, days):
        """Remove entries older than ``days`` days.

        :param days: Age threshold in days
        :return: Number of entries removed
        """
        if days is None or days < 0:
            return 0
        cutoff = time.time() - (days * 86400)
        removed = 0
        for path in list(self.entries.keys()):
            if self.entries[path].get("cached_at", 0) < cutoff:
                del self.entries[path]
                removed += 1
                self.dirty = True
        if removed:
            self.save()
        return removed

    def stats(self):
        """Return a dictionary of cache statistics."""
        size = (
            os.path.getsize(self.cache_path)
            if os.path.exists(self.cache_path)
            else 0
        )
        return {
            "cache_dir": self.cache_dir,
            "cache_file_size_bytes": size,
            "cached_files": len(self.entries),
            "format_version": FORMAT_VERSION,
        }

    def export(self, fileobj):
        """Export the cache to a JSON file object."""
        data = {
            "format_version": FORMAT_VERSION,
            "cache_key": self.cache_key,
            "exported_at": time.time(),
            "entries": self.entries,
        }
        json.dump(data, fileobj, sort_keys=True, indent=2)

    def import_cache(self, path):
        """Import and merge a previously exported cache file.

        Incompatible format versions and malformed input are discarded
        gracefully.
        """
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError) as e:
            LOG.warning("Ignoring malformed cache import %s: %s", path, e)
            return

        if not isinstance(data, dict):
            LOG.warning("Ignoring malformed cache import: %s", path)
            return
        if data.get("format_version") != FORMAT_VERSION:
            LOG.warning(
                "Ignoring cache import with incompatible format version: %s",
                path,
            )
            return

        entries = data.get("entries")
        if not isinstance(entries, dict):
            LOG.warning("Ignoring malformed cache import: %s", path)
            return

        merged = 0
        for entry_path, entry in entries.items():
            if self._valid_entry(entry):
                self.entries[entry_path] = entry
                merged += 1
            else:
                LOG.warning("Ignoring invalid cache entry from %s", path)
        if merged:
            self.dirty = True
            self.save()


def clear_cache_dir(cache_dir):
    """Remove the cache directory.  No-op if the directory is missing."""
    if os.path.isdir(cache_dir):
        shutil.rmtree(cache_dir)
EOF
python -m py_compile bandit/core/cache.py && echo OK