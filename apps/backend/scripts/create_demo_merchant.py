from __future__ import annotations

import argparse
from sqlalchemy import select
from core.security import generate_secret, sha256_text
from database.session import SessionLocal
from database.models import ApiKey, Application, Merchant


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a Ithute Pay Bridge merchant application and integration key")
    parser.add_argument("--name", default="LoanHub")
    parser.add_argument("--slug", default="loanhub")
    parser.add_argument("--environment", choices=["test", "live"], default="test")
    args = parser.parse_args()

    with SessionLocal() as db:
        merchant = db.scalar(select(Merchant).where(Merchant.slug == args.slug))
        if not merchant:
            merchant = Merchant(name=args.name, slug=args.slug)
            db.add(merchant); db.flush()
        app = db.scalar(select(Application).where(
            Application.merchant_id == merchant.id,
            Application.name == f"{args.name} {args.environment.title()}",
            Application.environment == args.environment,
        ))
        if not app:
            app = Application(merchant_id=merchant.id, name=f"{args.name} {args.environment.title()}", environment=args.environment)
            db.add(app); db.flush()
        prefix = "ipb_test_" if args.environment == "test" else "ipb_live_"
        secret = generate_secret(prefix, 32)
        key = ApiKey(application_id=app.id, name="Initial integration key", prefix=secret[:16],
                     secret_hash=sha256_text(secret), last4=secret[-4:], scopes=[])
        db.add(key); db.commit()
        print(f"Merchant: {merchant.name} ({merchant.id})")
        print(f"Application: {app.name} ({app.id})")
        print("API key (shown once):")
        print(secret)


if __name__ == "__main__":
    main()
