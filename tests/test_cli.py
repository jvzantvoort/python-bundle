import hashlib
import json

import pytest
from click.testing import CliRunner
from PIL import Image, TiffImagePlugin

from bundle_python.cli import main


@pytest.fixture
def bundle(tmp_path):
    (tmp_path / ".bundle").mkdir()
    (tmp_path / ".bundle" / "META.json").write_text("{}")
    img = Image.new("RGB", (40, 20))
    exif = Image.Exif()
    exif[0x010F] = "ACME"
    exif[0x0110] = "Cam 1"
    exif[0x0112] = 6  # rotated: axes swap
    img.save(tmp_path / "a.jpg", exif=exif)
    (tmp_path / "notes.txt").write_text("hi")
    lines = []
    for n in ("a.jpg", "notes.txt"):
        lines.append(f"{hashlib.sha256((tmp_path / n).read_bytes()).hexdigest()}  ./{n}")
    (tmp_path / ".bundle" / "SHA256SUM.txt").write_text("\n".join(lines) + "\n")
    return tmp_path


def run(*args):
    return CliRunner().invoke(main, [str(a) for a in args])


def test_scan_and_show(bundle):
    r = run("scan", bundle, "--json")
    assert r.exit_code == 0
    assert json.loads(r.output) == {"added": 1, "updated": 0, "skipped": 0, "unsupported": 1, "removed": 0}
    info = json.loads(run("show", bundle, "a.jpg").output)["a.jpg"]
    assert info["resolution"] == {"width": 20, "height": 40}
    assert info["device"] == {"make": "ACME", "model": "Cam 1"}
    assert json.loads(run("devices", bundle, "--json").output) == [
        {"make": "ACME", "model": "Cam 1", "files": 1}]
    assert "ACME Cam 1" in run("show", bundle).output


def test_rescan_skips_unchanged(bundle):
    run("scan", bundle)
    assert json.loads(run("scan", bundle, "--json").output)["skipped"] == 1


def test_exit_codes(bundle, tmp_path):
    assert run("scan", tmp_path / "nope").exit_code == 1
    assert run("show", bundle, "a.jpg").exit_code == 1
    run("scan", bundle)
    (bundle / ".bundle" / "MEDIA.json").write_text("{bad")
    assert run("show", bundle).exit_code == 2


def test_zero_denominator_is_stored_as_null(tmp_path):
    """Pillow turns a rational with a zero denominator into NaN, which is not valid JSON."""
    (tmp_path / ".bundle").mkdir()
    (tmp_path / ".bundle" / "META.json").write_text("{}")
    exif = Image.Exif()
    exif[0x010F] = "ACME"
    exif[0x011A] = TiffImagePlugin.IFDRational(0, 0)  # XResolution 0/0
    exif[0x011B] = TiffImagePlugin.IFDRational(72, 1)  # YResolution
    Image.new("RGB", (4, 2)).save(tmp_path / "lens.jpg", exif=exif)

    assert run("scan", tmp_path).exit_code == 0
    text = (tmp_path / ".bundle" / "MEDIA.json").read_text()
    assert "NaN" not in text
    stored = json.loads(text)["files"]["lens.jpg"]["exif"]
    assert stored["XResolution"] is None
    assert stored["YResolution"] == 72.0
