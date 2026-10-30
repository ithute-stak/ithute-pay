# IthutePay public domain contract

Production-facing domains (planned; DNS/TLS/reverse proxy deployment is separate):

- Portal: `https://portal.pay.ithute.co.ls`
- API origin: `https://api.pay.ithute.co.ls`

The frontend must call the API origin, not its own portal host. Preserve
any backend version prefix (see `API_V1_PREFIX`); an origin is not an endpoint.

## Deployment checklist

1. Point both DNS names to the appropriate reverse proxy. Verify DNS and HTTPS certificates.
2. Proxy the portal host to the frontend and API host to the backend.
3. Configure the frontend's public API base URL to `https://api.pay.ithute.co.ls`.
4. Restrict backend CORS to the approved portal origins. The current backend
   `CORS_ORIGINS` default already includes `https://portal.pay.ithute.co.ls`.
   Remove development and obsolete origins from the **production environment**
   after confirming any other authorized clients.
5. Configure payment-provider callback URLs only after inspecting actual API
   router paths; do not guess webhook routes or expose secret-bearing URLs.
6. Keep Golink collections and reconciliation disabled until sandbox certification.
7. Verify HTTPS, authenticated API calls, portal sign-in, callbacks, audit logs,
   health checks, rollback, and session/cookie security before production cutover.

These domains do not certify Golink or change payment routing.
