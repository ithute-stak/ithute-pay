# Golink retirement database preflight

From the backend directory in an authorised environment, run:

    python -m scripts.golink_retirement_audit

The command enforces a PostgreSQL read-only repeatable-read transaction and reports counts only, without keys, customer data, or raw payloads. Exit 0 means no normalized Golink provider rows or Golink-prefixed aliases were found in mapped provider columns; exit 1 means records require operator review; exit 2 means the audit could not be completed.

This is a first-pass inventory, not certification of settlement completion. Review aliases, linked reversals/charges, JSON metadata, provider-side statements, and any queued callbacks before removing credentials. Preserve all historical financial rows. Do not deploy retirement if unresolved payments or callbacks exist. Verify backup and restore, revoke obsolete keys with the provider and remove deployment secrets separately.
