from __future__ import annotations


class BuildInventoryError(ValueError):
    """A build inventory failure with a stable machine-readable code."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        distribution: str | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.distribution = distribution


def inventory_error(
    code: str,
    message: str,
    *,
    distribution: str | None = None,
) -> BuildInventoryError:
    return BuildInventoryError(code, message, distribution=distribution)


__all__ = ["BuildInventoryError"]
