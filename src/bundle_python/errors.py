class BundleError(Exception):
    """User error (exit code 1): bad path, not a bundle, missing entry."""


class SystemError_(Exception):
    """System error (exit code 2): I/O failure, corrupt metadata file."""
