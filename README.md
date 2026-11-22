# bundle-python

Extends a [bundle](../bundle)'s metadata with information looked up from its files: EXIF data,
resolution, capture time, GPS and the device (camera/phone) that made them.

Results go to `.bundle/MEDIA.json`. It is separate from `META.json` because the Go library
rewrites `META.json` from a fixed struct and would drop unknown fields. `.bundle/` is outside the
checksum, so the bundle identity never changes.

## Install

    pip install -e '.[dev]'

Images are read with Pillow. Videos need `ffprobe` (ffmpeg) on `PATH`; without it they are
skipped with a warning.

## Usage

    bundle-python scan BUNDLE [--force] [--json]   # extract and store
    bundle-python show BUNDLE [FILE] [--json]      # table, or full detail incl. EXIF for FILE
    bundle-python devices BUNDLE [--json]          # devices and file counts
    bundle-python clear BUNDLE                     # remove MEDIA.json

`scan` is incremental: files whose SHA256 in `SHA256SUM.txt` is unchanged are skipped
(`--force` overrides), and entries for files no longer in the bundle are removed.

Data goes to stdout; logs and errors to stderr (`-v`, `-vv`). Exit codes: `0` success,
`1` user error, `2` system error.

## Tests

    pytest
