"""Content versions for assets served with long-lived browser caches."""
import hashlib
from functools import lru_cache
from pathlib import Path

from config import BASE_DIR


def javascript_files(base_dir=None):
    base = Path(base_dir if base_dir is not None else BASE_DIR)
    return sorted(path for path in (base / "static/js").rglob("*.js") if path.is_file())


@lru_cache(maxsize=1)
def _hash_assets(base, snapshot):
    digest = hashlib.sha256()
    for relative, _mtime, _size in snapshot:
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update((base / relative).read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()[:10]


def get_asset_version(base_dir=None):
    base = Path(base_dir if base_dir is not None else BASE_DIR).resolve()
    files = javascript_files(base)
    files.extend(path for path in (base / "static/css").glob("*.css") if path.is_file())
    files.extend(path for path in (base / "static/sw.js", base / "VERSION") if path.is_file())
    snapshot = []
    for path in sorted(files):
        stat = path.stat()
        snapshot.append((path.relative_to(base).as_posix(), stat.st_mtime_ns, stat.st_size))
    return _hash_assets(base, tuple(snapshot))
