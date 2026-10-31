"""Provider-neutral routing policy for a gradual move to direct payment rails.

This module makes *decisions*, never executes payments. It is deliberately not
installed into the active provider registry: activation needs separate review.
Once an attempt is created, its provider must be immutable. Existing Golink
attempts remain eligible for reconciliation after new routing is disabled.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Rail = Literal["MPESA", "ECOCASH"]
Provider = Literal["direct", "golink"]


class RoutingUnavailable(ValueError):
    """No certified route exists; never silently fall back."""


@dataclass(frozen=True)
class RailRoutingPolicy:
    direct_certified: bool = False
    direct_enabled: bool = False
    golink_certified: bool = False
    golink_enabled_for_new: bool = False

    def __post_init__(self) -> None:
        for value in (
            self.direct_certified, self.direct_enabled,
            self.golink_certified, self.golink_enabled_for_new,
        ):
            if type(value) is not bool:
                raise TypeError("Routing policy values must be booleans")


def choose_new_payment_provider(rail: Rail, policy: RailRoutingPolicy) -> Provider:
    """Choose a provider only for a NEW attempt, preferring certified direct.

    Never call this method to reroute a submitted, pending, or unknown attempt.
    The caller must persist the selected provider alongside the attempt and
    its idempotency key before any external call.
    """
    if rail not in ("MPESA", "ECOCASH"):
        raise RoutingUnavailable("Unsupported mobile-money rail")
    if policy.direct_certified and policy.direct_enabled:
        return "direct"
    if policy.golink_certified and policy.golink_enabled_for_new:
        return "golink"
    raise RoutingUnavailable("No certified and enabled provider for new payments")


def provider_for_existing_attempt(provider: str, *, state: str) -> Provider:
    """Keep reconciliation on the original provider despite routing changes."""
    if provider not in ("direct", "golink"):
        raise RoutingUnavailable("Invalid original payment provider")
    if state not in ("created", "processing", "unknown", "succeeded", "failed", "cancelled"):
        raise RoutingUnavailable("Invalid original attempt state")
    return provider
