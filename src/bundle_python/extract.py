"""Extract media metadata (EXIF, resolution, device) from a single file."""

from __future__ import annotations

import functools
import json
import logging
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import ExifTags, Image, UnidentifiedImageError

log = logging.getLogger("bundle_python")

VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".webm", ".mts", ".3gp"}
ORIENTATION_SWAPS_AXES = {5, 6, 7, 8}


def _plain(value: Any) -> Any:
    """Convert EXIF values to JSON-serialisable plain types."""
    if isinstance(value, bytes):
        text = value.decode("utf-8", "replace").strip("\x00 ")
        return text if text.isprintable() else f"<{len(value)} bytes>"
    if isinstance(value, (tuple, list)):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (int, str, bool)) or value is None:
        return value
    try:  # IFDRational and friends
        return float(value)
    except (TypeError, ValueError):
        return str(value)


def _read_exif(img: Image.Image) -> dict[str, Any]:
    exif = img.getexif()
    out: dict[str, Any] = {}
    sources = [(exif, "")]
    for ifd in (ExifTags.IFD.Exif, ExifTags.IFD.GPSInfo):
        try:
            sources.append((exif.get_ifd(ifd), ifd.name))
        except Exception:  # damaged sub-IFD: keep what we have
            log.warning("unreadable EXIF IFD %s", ifd.name)
    for tags, prefix in sources:
        names = ExifTags.GPSTAGS if prefix == "GPSInfo" else ExifTags.TAGS
        for tag, value in tags.items():
            if tag in (ExifTags.IFD.Exif, ExifTags.IFD.GPSInfo, ExifTags.IFD.Interop):
                continue
            name = names.get(tag, f"Tag{tag}")
            out[f"GPS{name}" if prefix == "GPSInfo" else name] = _plain(value)
    out.pop("MakerNote", None)
    out.pop("UserComment", None)
    return out


def _gps(exif: dict[str, Any]) -> dict[str, float] | None:
    def deg(vals: Any, ref: Any) -> float | None:
        try:
            d, m, s = vals
            res = d + m / 60 + s / 3600
            return -res if ref in ("S", "W") else res
        except (TypeError, ValueError):
            return None

    lat = deg(exif.get("GPSGPSLatitude"), exif.get("GPSGPSLatitudeRef"))
    lon = deg(exif.get("GPSGPSLongitude"), exif.get("GPSGPSLongitudeRef"))
    if lat is None or lon is None:
        return None
    return {"latitude": round(lat, 6), "longitude": round(lon, 6)}


def _device(exif: dict[str, Any]) -> dict[str, str] | None:
    keys = {"make": "Make", "model": "Model", "lens": "LensModel", "software": "Software"}
    dev = {}
    for k, v in keys.items():
        text = str(exif.get(v) or "").split("\x00")[0].strip()  # some cameras pad with NULs/garbage
        if text and text.isprintable():
            dev[k] = text
    return dev or None


def _image(path: Path) -> dict[str, Any]:
    with Image.open(path) as img:
        width, height = img.size
        exif = _read_exif(img)
        info: dict[str, Any] = {"type": "image", "format": img.format}
    if exif.get("Orientation") in ORIENTATION_SWAPS_AXES:
        width, height = height, width
    info["resolution"] = {"width": width, "height": height}
    if exif:
        info["exif"] = exif
        taken = exif.get("DateTimeOriginal") or exif.get("DateTime")
        if taken:
            info["taken_at"] = str(taken)
        if (dev := _device(exif)):
            info["device"] = dev
        if (gps := _gps(exif)):
            info["gps"] = gps
    return info


@functools.lru_cache(maxsize=1)
def _warn_no_ffprobe() -> None:
    log.warning("ffprobe not found: video files are skipped (install ffmpeg)")


@functools.lru_cache(maxsize=1)
def _warn_probe_failed() -> None:
    log.warning("ffprobe failed on some videos; use -vv to see which. An ffmpeg build without a "
                "real H.264 decoder (e.g. ffmpeg-free + noopenh264) cannot probe H.264 files.")


def _video(path: Path) -> dict[str, Any] | None:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        log.debug("ffprobe not found, skipping video %s", path)
        _warn_no_ffprobe()
        return None
    proc = subprocess.run(
        [ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True, timeout=60,
    )
    if proc.returncode != 0:
        log.debug("ffprobe failed for %s: %s", path, proc.stderr.strip())
        _warn_probe_failed()
        return None
    data = json.loads(proc.stdout)
    info: dict[str, Any] = {"type": "video"}
    fmt = data.get("format", {})
    if fmt.get("duration"):
        info["duration_seconds"] = round(float(fmt["duration"]), 3)
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video":
            info["resolution"] = {"width": stream.get("width"), "height": stream.get("height")}
            info["codec"] = stream.get("codec_name")
            break
    tags = {k.lower(): v for k, v in fmt.get("tags", {}).items()}
    dev = {}
    for key, names in {
        "make": ("com.apple.quicktime.make", "make"),
        "model": ("com.apple.quicktime.model", "model"),
        "software": ("com.apple.quicktime.software", "encoder"),
    }.items():
        for n in names:
            if tags.get(n):
                dev[key] = tags[n]
                break
    if dev:
        info["device"] = dev
    if tags.get("creation_time"):
        info["taken_at"] = tags["creation_time"]
    return info


def extract(path: Path) -> dict[str, Any] | None:
    """Return media info for ``path`` or None when the file is not a supported media file."""
    if path.suffix.lower() in VIDEO_EXTENSIONS:
        return _video(path)
    try:
        return _image(path)
    except (UnidentifiedImageError, Image.DecompressionBombError):
        return None


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
