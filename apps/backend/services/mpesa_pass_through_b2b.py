"""Internal non-executing B2B transaction preparation."""
from sqlalchemy import select
from sqlalchemy.orm import Session
from database.models import Application, MerchantCommercialAgreement
from services.mpesa_pass_through_readiness import check_b2b_readiness
from services.mpesa_pass_through_quotes import quote_from_agreement
from services.mpesa_pass_through_store import create_quote_record
from services.mpesa_pass_through_lifecycle import TransactionError


def prepare_b2b(db: Session, *, sender_merchant_id: str, recipient_merchant_id: str,
                application_id: str, idempotency_key: str, principal: object):
    """Trusted backend only. No provider call or execution authorization."""
    app = db.get(Application, application_id)
    if app is None or app.merchant_id != sender_merchant_id or app.environment not in {"test", "live"}:
        raise TransactionError("Application outside sender scope")
    environment = "sandbox" if app.environment == "test" else "production"
    ready = check_b2b_readiness(db, sender_merchant_id=sender_merchant_id,
                                recipient_merchant_id=recipient_merchant_id, environment=environment)
    agreement = db.scalar(select(MerchantCommercialAgreement).where(
        MerchantCommercialAgreement.merchant_id == sender_merchant_id,
        MerchantCommercialAgreement.version == ready.sender_agreement_version,
        MerchantCommercialAgreement.status == "approved",
        MerchantCommercialAgreement.currency == "LSL",
    ))
    q = quote_from_agreement(sender_merchant_id, "outgoing", principal, agreement,
                             transaction_type="b2b")
    return create_quote_record(db, merchant_id=sender_merchant_id, application_id=application_id,
        idempotency_key=idempotency_key, request={"principal": str(q.principal), "recipient": recipient_merchant_id},
        quote=q, b2b_parties={"sender": ready.sender_shortcode, "gateway": ready.gateway_shortcode,
                            "recipient": ready.recipient_shortcode, "recipient_merchant_id": recipient_merchant_id,
                            "environment": environment})
