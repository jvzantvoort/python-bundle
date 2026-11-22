"""Click CLI. Data goes to stdout, logs and errors to stderr. Exit codes: 0 ok, 1 user, 2 system."""

from __future__ import annotations

import json
import logging
import sys

import click

from . import __version__, store
from .errors import BundleError, SystemError_


def _emit(obj) -> None:
    click.echo(json.dumps(obj, indent=2, sort_keys=True))


def _table(rows: list[list[str]], header: list[str]) -> None:
    widths = [max(len(str(r[i])) for r in [header, *rows]) for i in range(len(header))]
    for r in [header, *rows]:
        click.echo("  ".join(str(c).ljust(w) for c, w in zip(r, widths)).rstrip())


def _res(info: dict) -> str:
    r = info.get("resolution")
    return f"{r['width']}x{r['height']}" if r else "-"


def _dev(info: dict) -> str:
    d = info.get("device") or {}
    return " ".join(x for x in (d.get("make"), d.get("model")) if x) or "-"


@click.group()
@click.version_option(__version__, prog_name="bundle-python")
@click.option("-v", "--verbose", count=True, help="-v for INFO, -vv for DEBUG logging.")
def main(verbose: int) -> None:
    """Extend a bundle's metadata with EXIF data, resolution and device info.

    Results are stored in BUNDLE/.bundle/MEDIA.json and never change the bundle checksum.
    """
    level = {0: logging.WARNING, 1: logging.INFO}.get(verbose, logging.DEBUG)
    logging.basicConfig(level=level, stream=sys.stderr, format="%(levelname)s %(message)s")


def _run(fn):
    """Map library errors to exit codes."""
    try:
        return fn()
    except BundleError as e:
        click.echo(f"error: {e}", err=True)
        sys.exit(1)
    except SystemError_ as e:
        click.echo(f"error: {e}", err=True)
        sys.exit(2)


path_arg = click.argument("bundle", type=click.Path(file_okay=False))
json_opt = click.option("--json", "as_json", is_flag=True, help="Machine readable output.")


@main.command()
@path_arg
@click.option("--force", is_flag=True, help="Re-extract files whose checksum is unchanged.")
@json_opt
def scan(bundle: str, force: bool, as_json: bool) -> None:
    """Look up metadata of all media files in BUNDLE and store it."""
    summary = _run(lambda: store.scan(store.bundle_dir(bundle), force=force))
    if as_json:
        _emit(summary)
    else:
        click.echo(", ".join(f"{k}: {v}" for k, v in summary.items()))


@main.command()
@path_arg
@click.argument("file", required=False)
@json_opt
def show(bundle: str, file: str | None, as_json: bool) -> None:
    """Show stored metadata: a table of all files, or full detail (with EXIF) for FILE."""
    def go():
        data = store.load(store.bundle_dir(bundle))
        if file is None:
            return data
        key = file[2:] if file.startswith("./") else file
        if key not in data["files"]:
            raise BundleError(f"no stored metadata for {file}; run 'scan' first")
        return {key: data["files"][key]}

    data = _run(go)
    if as_json or file is not None:
        _emit(data)
    else:
        rows = [[p, i.get("type", "-"), _res(i), _dev(i), i.get("taken_at", "-")]
                for p, i in sorted(data["files"].items())]
        _table(rows, ["FILE", "TYPE", "RESOLUTION", "DEVICE", "TAKEN"])


@main.command()
@path_arg
@json_opt
def devices(bundle: str, as_json: bool) -> None:
    """List the devices that produced the files in BUNDLE."""
    devs = _run(lambda: store.devices(store.load(store.bundle_dir(bundle))))
    if as_json:
        _emit(devs)
    else:
        _table([[d.get("make", "-"), d.get("model", "-"), d.get("lens", "-"), d["files"]] for d in devs],
               ["MAKE", "MODEL", "LENS", "FILES"])


@main.command()
@path_arg
def clear(bundle: str) -> None:
    """Remove the stored media metadata of BUNDLE."""
    removed = _run(lambda: store.clear(store.bundle_dir(bundle)))
    click.echo("removed" if removed else "nothing to remove")
