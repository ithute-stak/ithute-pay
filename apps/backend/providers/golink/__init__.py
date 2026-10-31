"""Optional Golink Transact provider; never replaces direct M-Pesa."""
from .client import GolinkClient, GolinkError, GolinkConfigurationError

__all__ = ["GolinkClient", "GolinkError", "GolinkConfigurationError"]
