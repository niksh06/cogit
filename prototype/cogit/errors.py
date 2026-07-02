"""Cogit error hierarchy mapped to CLI exit codes (docs/spec/cli-contract.md)."""


class CogitError(Exception):
    """Base error. exit_code follows the CLI contract."""

    exit_code = 1


class UserError(CogitError):
    """Invalid input, unresolved conflict, or verification failure."""

    exit_code = 1


class RepositoryNotFound(CogitError):
    """No .cogit repository found or layout invalid."""

    exit_code = 2


class CorruptionError(CogitError):
    """Object corruption: bad zlib, header, size, hash-path mismatch, schema."""

    exit_code = 3


class ConcurrentUpdateError(CogitError):
    """Lock contention or old-target mismatch during a ref update."""

    exit_code = 4


class UnsupportedFormatError(CogitError):
    """Repository format version or required extension not supported."""

    exit_code = 5
