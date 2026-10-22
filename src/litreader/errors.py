"""Fail-closed error types. Every error aborts the current step."""


class LitError(Exception):
    """Base error."""


class SandboxViolation(LitError):
    """Path escapes the permitted root or traverses a link."""


class AlreadyExists(LitError):
    """Exclusive create refused: target already exists."""


class HashMismatch(LitError):
    """Compare-hash failed (concurrent or user modification) or post-write verify failed."""


class ProtectedZoneError(LitError):
    """User-annotation zone markers missing, duplicated or malformed."""


class InvalidTransition(LitError):
    """Publication state machine refused a transition."""


class Stop(LitError):
    """Generic STOP requiring a human decision."""
