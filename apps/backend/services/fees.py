from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from database.models import (
    FeePackage,
    FeePackageRule,
    FeeRule,
    MerchantFeePackage,
    ProviderTransaction,
)

CENT = Decimal("0.01")
ZERO = Decimal("0.00")


@dataclass(frozen=True)
class FeeCalculation:
    amount: Decimal
    fixed_fee: Decimal
    percentage_fee: Decimal
    minimum_fee: Decimal | None
    maximum_fee: Decimal | None
    source: str
    source_id: str | None
    payer: str = "merchant"


def _money(value: Decimal | str | int | float | None) -> Decimal:
    return Decimal(value or 0).quantize(CENT, rounding=ROUND_HALF_UP)


def operation_type(transaction: ProviderTransaction) -> str:
    return {
        "payment_intent": "collection",
        "mandate_charge": "collection",
        "payout": "payout",
        "transfer": "transfer",
    }.get(transaction.resource_type, transaction.resource_type)


def _amount_from_rule(
    gross: Decimal,
    *,
    fixed_fee: Decimal,
    percentage_fee: Decimal,
    minimum_fee: Decimal | None = None,
    maximum_fee: Decimal | None = None,
) -> Decimal:
    fee = Decimal(fixed_fee or 0) + (gross * Decimal(percentage_fee or 0) / Decimal("100"))
    if minimum_fee is not None:
        fee = max(fee, Decimal(minimum_fee))
    if maximum_fee is not None:
        fee = min(fee, Decimal(maximum_fee))
    # Never let a merchant-paid gateway fee make the settlement negative.
    fee = min(fee, gross)
    return fee.quantize(CENT, rounding=ROUND_HALF_UP)


def _legacy_rule(db: Session, transaction: ProviderTransaction, *, merchant_specific: bool) -> FeeRule | None:
    op = operation_type(transaction)
    merchant_clause = (
        FeeRule.merchant_id == transaction.merchant_id
        if merchant_specific
        else FeeRule.merchant_id.is_(None)
    )
    return db.scalar(
        select(FeeRule).where(
            FeeRule.active.is_(True),
            FeeRule.operation_type == op,
            or_(FeeRule.provider == transaction.provider, FeeRule.provider.is_(None)),
            merchant_clause,
        ).order_by(FeeRule.provider.desc().nullslast(), FeeRule.created_at.desc())
    )


def _package_rule(db: Session, package_id: str, transaction: ProviderTransaction) -> FeePackageRule | None:
    return db.scalar(
        select(FeePackageRule).where(
            FeePackageRule.fee_package_id == package_id,
            FeePackageRule.active.is_(True),
            FeePackageRule.operation_type == operation_type(transaction),
            or_(FeePackageRule.provider == transaction.provider, FeePackageRule.provider.is_(None)),
        ).order_by(FeePackageRule.provider.desc().nullslast(), FeePackageRule.created_at.desc())
    )


def calculate_fee_details(db: Session, transaction: ProviderTransaction) -> FeeCalculation:
    gross = _money(transaction.amount)

    # 1. Explicit per-merchant legacy override. This remains the strongest rule
    #    so existing deployments keep their configured commercial agreements.
    rule = _legacy_rule(db, transaction, merchant_specific=True)
    if rule:
        amount = _amount_from_rule(
            gross,
            fixed_fee=Decimal(rule.fixed_fee or 0),
            percentage_fee=Decimal(rule.percentage_fee or 0),
        )
        return FeeCalculation(
            amount=amount,
            fixed_fee=_money(rule.fixed_fee),
            percentage_fee=Decimal(rule.percentage_fee or 0),
            minimum_fee=None,
            maximum_fee=None,
            source="merchant_override",
            source_id=rule.id,
            payer=rule.payer,
        )

    # 2. Package explicitly assigned to this merchant.
    assignment = db.scalar(
        select(MerchantFeePackage).where(
            MerchantFeePackage.merchant_id == transaction.merchant_id,
            MerchantFeePackage.active.is_(True),
        )
    )
    if assignment:
        package = db.get(FeePackage, assignment.fee_package_id)
        package_rule = _package_rule(db, assignment.fee_package_id, transaction)
        if package and package.active and package_rule:
            amount = _amount_from_rule(
                gross,
                fixed_fee=Decimal(package_rule.fixed_fee or 0),
                percentage_fee=Decimal(package_rule.percentage_fee or 0),
                minimum_fee=package_rule.minimum_fee,
                maximum_fee=package_rule.maximum_fee,
            )
            return FeeCalculation(
                amount=amount,
                fixed_fee=_money(package_rule.fixed_fee),
                percentage_fee=Decimal(package_rule.percentage_fee or 0),
                minimum_fee=_money(package_rule.minimum_fee) if package_rule.minimum_fee is not None else None,
                maximum_fee=_money(package_rule.maximum_fee) if package_rule.maximum_fee is not None else None,
                source=f"package:{package.code}",
                source_id=package_rule.id,
                payer=package_rule.payer,
            )

    # 3. Existing global fee rule.
    rule = _legacy_rule(db, transaction, merchant_specific=False)
    if rule:
        amount = _amount_from_rule(
            gross,
            fixed_fee=Decimal(rule.fixed_fee or 0),
            percentage_fee=Decimal(rule.percentage_fee or 0),
        )
        return FeeCalculation(
            amount=amount,
            fixed_fee=_money(rule.fixed_fee),
            percentage_fee=Decimal(rule.percentage_fee or 0),
            minimum_fee=None,
            maximum_fee=None,
            source="global_override",
            source_id=rule.id,
            payer=rule.payer,
        )

    # 4. Default commercial package for merchants that have not been assigned one.
    default_package = db.scalar(
        select(FeePackage).where(FeePackage.active.is_(True), FeePackage.is_default.is_(True))
        .order_by(FeePackage.updated_at.desc())
    )
    if default_package:
        package_rule = _package_rule(db, default_package.id, transaction)
        if package_rule:
            amount = _amount_from_rule(
                gross,
                fixed_fee=Decimal(package_rule.fixed_fee or 0),
                percentage_fee=Decimal(package_rule.percentage_fee or 0),
                minimum_fee=package_rule.minimum_fee,
                maximum_fee=package_rule.maximum_fee,
            )
            return FeeCalculation(
                amount=amount,
                fixed_fee=_money(package_rule.fixed_fee),
                percentage_fee=Decimal(package_rule.percentage_fee or 0),
                minimum_fee=_money(package_rule.minimum_fee) if package_rule.minimum_fee is not None else None,
                maximum_fee=_money(package_rule.maximum_fee) if package_rule.maximum_fee is not None else None,
                source=f"default_package:{default_package.code}",
                source_id=package_rule.id,
                payer=package_rule.payer,
            )

    return FeeCalculation(
        amount=ZERO,
        fixed_fee=ZERO,
        percentage_fee=Decimal("0.0000"),
        minimum_fee=None,
        maximum_fee=None,
        source="none",
        source_id=None,
    )


def calculate_fee(db: Session, transaction: ProviderTransaction) -> Decimal:
    return calculate_fee_details(db, transaction).amount
