"""Validated, per-rail administrator configuration for future provider migration.

This configuration is an immutable policy snapshot, not a live routing switch.
The active IthutePay provider registry is intentionally not changed.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from integrations.rail_routing_policy import (
    RailRoutingPolicy, Provider, choose_new_payment_provider,
)

SUPPORTED_RAILS = frozenset({"MPESA", "ECOCASH"})
FIELDS = frozenset({
    "direct_certified", "direct_enabled",
    "golink_certified", "golink_enabled_for_new",
})


@dataclass(frozen=True)
class RoutingConfiguration:
    mpesa: RailRoutingPolicy
    ecocash: RailRoutingPolicy

    @classmethod
    def from_admin_settings(cls, settings: Mapping[str, object]) -> "RoutingConfiguration":
        """Parse an explicit snapshot without unsafe boolean coercion or defaults."""
        if not isinstance(settings, Mapping) or set(settings) != SUPPORTED_RAILS:
            raise ValueError("Expected separate MPESA and ECOCASH routing settings")

        parsed: dict[str, RailRoutingPolicy] = {}
        for rail in ("MPESA", "ECOCASH"):
            values = settings[rail]
            if not isinstance(values, Mapping) or set(values) != FIELDS:
                raise ValueError(f"Invalid {rail} provider routing fields")
            if any(type(value) is not bool for value in values.values()):
                raise ValueError(f"{rail} routing settings must be boolean")
            parsed[rail] = RailRoutingPolicy(**dict(values))

        return cls(mpesa=parsed["MPESA"], ecocash=parsed["ECOCASH"])

    def for_new_attempt(self, rail: str) -> Provider:
        if rail == "MPESA":
            return choose_new_payment_provider("MPESA", self.mpesa)
        if rail == "ECOCASH":
            return choose_new_payment_provider("ECOCASH", self.ecocash)
        raise ValueError("Unsupported payment rail")
