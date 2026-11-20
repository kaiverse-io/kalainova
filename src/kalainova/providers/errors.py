"""How a vendor call fails, in the engine's terms (ADR 0023). A transport raises these from what the
vendor answered, and the router decides on them: move on to the next provider, settle what was
billed, or stop. Imported through providers/contract.py."""

from __future__ import annotations


class VendorError(RuntimeError):
    """A vendor call failed in a way the router can act on. Adapters raise a subclass."""


class BilledError(VendorError):
    """The vendor charged for this call, and then the file could not be fetched.

    Raised by an adapter so the ledger still records the money.
    """

    def __init__(self, billed: float, message: str) -> None:
        super().__init__(message)
        self.billed = billed


class RefusalError(VendorError):
    """The model or provider declined the request under its policy."""


class InvalidRequestError(VendorError):
    """The vendor refused the request as malformed (a field it does not take, a value out of range).

    That is a fault in the engine's mapping, so the router stops instead of spending on the next
    listed provider."""


class UnauthorizedError(VendorError):
    """The vendor refused the key: missing, wrong, or without the permission the call needs."""


class RateLimitedError(VendorError):
    """The vendor asked us to slow down."""


class UnavailableError(VendorError):
    """The vendor could not be reached or failed on its side."""


class RetiredError(UnavailableError):
    """The vendor says the route is gone for good (HTTP 410). Asking again finds nothing, so the
    route is written down as retired (providers/retired.py)."""
