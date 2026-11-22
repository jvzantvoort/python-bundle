"""Read and write the extended metadata file of a bundle.

The Go library rewrites META.json from a fixed struct and would drop unknown fields, so the
extension lives next to it in ``.bundle/MEDIA.json``. ``.bundle/`` is excluded from the bundle
checksum, so this never changes a bundle's identity.
"""

from __future__ import annotations

import json
import math
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Iterator

from . import __version__
from .errors import BundleError, SystemError_
from .extract import extract, now

MEDIA_FILE = "MEDIA.json"
SCHEMA_VERSION = 1
_CHECKSUM_LINE = re.compile(r"^([0-9a-f]{64}) [ *]?(.+)$")


def bundle_dir(path: str | Path) -> Path:
    root = Path(path)
    if not (root / ".bundle" / "META.json").is_file():
        raise BundleError(f"{root} is not a bundle (no .bundle/META.json)")
    return root


def manifest(root: Path) -> dict[str, str]:
    """Map relative path -> sha256 from SHA256SUM.txt."""
    sums = root / ".bundle" / "SHA256SUM.txt"
    entries: dict[str, str] = {}
    if not sums.is_file():
        return entries
    for line in sums.read_text(encoding="utf-8").splitlines():
        m = _CHECKSUM_LINE.match(line)
        if m:
            rel = m.group(2)
            entries[rel[2:] if rel.startswith("./") else rel] = m.group(1)
    return entries


def _iter_files(root: Path, entries: dict[str, str]) -> Iterator[str]:
    if entries:
        yield from sorted(entries)
        return
    for dirpath, dirnames, filenames in os.walk(root):
        if ".bundle" in dirnames:
            dirnames.remove(".bundle")
        for name in filenames:
            yield str((Path(dirpath) / name).relative_to(root))


def load(root: Path) -> dict[str, Any]:
    f = root / ".bundle" / MEDIA_FILE
    if not f.exists():
        return {"version": SCHEMA_VERSION, "files": {}}
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise SystemError_(f"cannot read {f}: {e}") from e
    data.setdefault("files", {})
    return data


def _finite(value: Any) -> Any:
    """Replace NaN and infinities with None: they are not valid JSON, and other readers
    (bundle-server, the Go bundle CLI) reject a file that contains them."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: _finite(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_finite(v) for v in value]
    return value


def save(root: Path, data: dict[str, Any]) -> None:
    target = root / ".bundle" / MEDIA_FILE
    try:
        fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".media-")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(_finite(data), fh, indent=2, sort_keys=True, allow_nan=False)
            fh.write("\n")
        os.chmod(tmp, 0o644)
        os.replace(tmp, target)
    except OSError as e:
        raise SystemError_(f"cannot write {target}: {e}") from e


def scan(root: Path, *, force: bool = False) -> dict[str, Any]:
    """Extract media info for every supported file and store it. Returns a summary."""
    entries = manifest(root)
    data = load(root)
    files: dict[str, Any] = data["files"]
    added = updated = skipped = unsupported = 0
    seen = set()
    for rel in _iter_files(root, entries):
        seen.add(rel)
        full = root / rel
        if not full.is_file():
            continue
        sha = entries.get(rel)
        old = files.get(rel)
        if old and not force and sha and old.get("sha256") == sha:
            skipped += 1
            continue
        try:
            info = extract(full)
        except OSError as e:
            raise SystemError_(f"cannot read {full}: {e}") from e
        if info is None:
            unsupported += 1
            continue
        if sha:
            info["sha256"] = sha
        files[rel] = info
        if old:
            updated += 1
        else:
            added += 1
    removed = [k for k in files if k not in seen]
    for k in removed:
        del files[k]
    data.update(version=SCHEMA_VERSION, generator=f"bundle-python {__version__}", updated_at=now())
    data["devices"] = devices(data)
    save(root, data)
    return {"added": added, "updated": updated, "skipped": skipped,
            "unsupported": unsupported, "removed": len(removed)}


def devices(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Distinct devices with file counts, most used first."""
    counts: dict[tuple, int] = {}
    for info in data["files"].values():
        dev = info.get("device")
        if dev:
            key = tuple(sorted(dev.items()))
            counts[key] = counts.get(key, 0) + 1
    out = [{**dict(k), "files": n} for k, n in counts.items()]
    return sorted(out, key=lambda d: (-d["files"], d.get("make", ""), d.get("model", "")))


def clear(root: Path) -> bool:
    f = root / ".bundle" / MEDIA_FILE
    if not f.exists():
        return False
    try:
        f.unlink()
    except OSError as e:
        raise SystemError_(f"cannot remove {f}: {e}") from e
    return True
