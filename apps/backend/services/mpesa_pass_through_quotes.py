"""Non-posting M-Pesa pass-through commercial quotes.

This module must not invoke providers or mutate balances. Rates are percentages
(1 means 1%) and are loaded from approved merchant agreements when available.
Provider costs are estimates until reconciled against actual M-Pesa evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

CENT = Decimal("0.01")


def money(value: object) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Invalid monetary input") from exc
    if not number.is_finite():
        raise ValueError("Non-finite monetary input")
    return number.quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Rate:
    percent: Decimal = Decimal("1")
    fixed: Decimal = Decimal("0")
    minimum: Decimal = Decimal("0")
    maximum: Decimal | None = None

    def __post_init__(self) -> None:
        if not 0 <= self.percent <= 100:
            raise ValueError("Invalid percentage rate")
        if self.fixed < 0 or self.minimum < 0:
            raise ValueError("Negative fees are prohibited")
        if self.maximum is not None and self.maximum < self.minimum:
            raise ValueError("Maximum is below minimum")

    def calculate(self, amount: Decimal) -> Decimal:
        result = max(self.minimum, self.fixed + amount * self.percent / 100)
        if self.maximum is not None:
            result = min(result, self.maximum)
        return money(result)


@dataclass(frozen=True)
class Quote:
    tenant_id: str
    agreement_version: int
    direction: str
    principal: Decimal
    provider_cost: Decimal
    ithutepay_fee: Decimal
    funding_amount: Decimal
    onward_amount: Decimal
    fee_payer: str

    def payload(self) -> dict[str, str | int]:
        return {
            "tenant_id": self.tenant_id,
            "agreement_version": self.agreement_version,
            "direction": self.direction,
            "principal": str(self.principal),
            "provider_cost": str(self.provider_cost),
            "ithutepay_fee": str(self.ithutepay_fee),
            "funding_amount": str(self.funding_amount),
            "onward_amount": str(self.onward_amount),
            "fee_payer": self.fee_payer,
            "currency": "LSL",
            "execution_enabled": "false",
        }


def quote(
    *,
    tenant_id: str,
    direction: str,
    principal: object,
    agreement_version: int = 1,
    incoming_rate: Rate = Rate(),
    outgoing_rate: Rate = Rate(),
    provider_incoming_rate: Rate = Rate(percent=Decimal("1")),
    provider_outgoing_rate: Rate = Rate(percent=Decimal("0")),
    provider_cost_payer: str = "tenant",
    approved: bool = False,
    custody_mode: str = "own_shortcode",
) -> Quote:
    if not approved or custody_mode != "own_shortcode":
        raise PermissionError("Approved own-shortcode tenant required")
    if not tenant_id or agreement_version < 1:
        raise ValueError("Invalid tenant or agreement")
    if direction not in {"incoming", "outgoing"}:
        raise ValueError("Unsupported direction")
    if provider_cost_payer not in {"tenant", "ithute"}:
        raise ValueError("Invalid provider cost payer")
    amount = money(principal)
    if amount <= 0 or Decimal(str(principal)) != amount:
        raise ValueError("Positive two-decimal amount required")

    ithute = (incoming_rate if direction == "incoming" else outgoing_rate).calculate(amount)
    cost = (provider_incoming_rate if direction == "incoming" else provider_outgoing_rate).calculate(amount)
    tenant_cost = cost if provider_cost_payer == "tenant" else Decimal("0.00")

    if direction == "outgoing":
        funding, onward = money(amount + ithute + tenant_cost), amount
    else:
        funding, onward = amount, money(amount - ithute - tenant_cost)
        if onward <= 0:
            raise ValueError("Fees exceed incoming proceeds")

    return Quote(
        tenant_id, agreement_version, direction, amount, cost,
        ithute, funding, onward, provider_cost_payer,
    )


def quote_from_agreement(tenant_id: str, direction: str, principal: object, agreement: object) -> Quote:
    """Adapt an already-authorized MerchantCommercialAgreement; caller checks tenancy.

    Deliberately does not query the database or take an untrusted merchant ID
    from an API body. Only approved agreements may be used.
    """
    if getattr(agreement, "status", None) != "approved" or getattr(agreement, "merchant_id", None) != tenant_id:
        raise PermissionError("Approved matching tenant agreement required")
    prefix = "inbound" if direction == "incoming" else "outbound"
    tariff = Rate(
        percent=Decimal(str(getattr(agreement, prefix + "_percentage_fee"))),
        fixed=Decimal(str(getattr(agreement, prefix + "_fixed_fee"))),
    )
    return quote(
        tenant_id=tenant_id, direction=direction, principal=principal,
        agreement_version=int(getattr(agreement, "version")),
        incoming_rate=tariff if direction == "incoming" else Rate(),
        outgoing_rate=tariff if direction == "outgoing" else Rate(),
        provider_cost_payer=str(getattr(agreement, "provider_cost_payer")),
        approved=True,
    )
