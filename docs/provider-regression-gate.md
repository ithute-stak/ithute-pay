# Offline provider regression gate

The provider regression workflow runs against an isolated PostgreSQL database with live M-PESA and push disabled. It retains direct M-PESA callback, response classification, concurrency and staging contract tests. Retirement tests verify that Golink cannot be configured, selected or imported and that its callback and scheduled worker are absent.

Historical payment records must remain unchanged. Before deploying the retirement, reconcile unresolved legacy attempts and callbacks, verify backups and revoke obsolete provider credentials. A passing offline suite is not evidence of live provider certification.
