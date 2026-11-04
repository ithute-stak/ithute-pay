# IthutePay Flutter mobile + web starter

A separate Flutter UI for `pay.ithute.co.ls`. This is a preview, NOT an
authenticated banking interface. All payment actions are deliberately inert.
The existing IthutePay backend (port 8001) and merchant Next.js portal (port
3001) remain unchanged.

## Local development

Install a compatible Flutter SDK, then:

```bash
cd apps/flutter_pay
flutter pub get
flutter run -d chrome
```

This Flutter source can later be built for Android and iOS after normal
platform scaffolding, app signing, authentication, and security review.

## Safe VPS deployment

Run the following on the VPS after merging the code into main. The new
container is *separate* and does not bind host ports or replace the payment API.

```bash
cd ~/ithute-pay
git fetch origin
git pull --ff-only
cd apps/flutter_pay
sudo docker compose -f compose.flutter-web.yml build
sudo docker compose -f compose.flutter-web.yml up -d --no-deps
sudo docker inspect ithutepay-flutter-web --format '{{.State.Health.Status}}'
```

Use the Caddy route below **only** for `pay.ithute.co.ls`, preserving the
existing portal and API host blocks:

```caddyfile
pay.ithute.co.ls {
    encode zstd gzip
    header X-Content-Type-Options "nosniff"
    header X-Frame-Options "DENY"
    header Referrer-Policy "strict-origin-when-cross-origin"
    reverse_proxy ithutepay-flutter-web:80
}
```

Caddy reads `/data/product-routes/ithutepay.caddy`, backed by the volume
`/var/lib/docker/volumes/ithute_ithute_caddy_data/_data`. Back that file up
before appending the new host block; inspect for any existing
`pay.ithute.co.ls` block first. Validate using:

```bash
sudo docker exec ithute-caddy-1 caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
```

Then reload, without restarting the shared proxy:

```bash
sudo docker exec ithute-caddy-1 caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
```

Verify `https://pay.ithute.co.ls`, the existing merchant portal, and API
health independently. Do not enable live payment rails as part of UI deployment.


## Phase 3 — Protected read-only session visibility

The Flutter Profile tab requests `GET /mobile-session` from the web origin.
Nginx forwards **only that exact GET path** to the existing backend
`GET /api/v1/auth/me` endpoint; it does not expose backend login,
refresh, payment, or administrative mutations.

- The existing product-local authentication dependency authorizes each request.
- An unauthenticated request must return HTTP 401 or 403; never return another user's identity.
- Nginx adds `Cache-Control: no-store, private` for all responses.
- The page does not read, save or expose access tokens, API keys, passwords, or payment details.
- The response displays the backend's `full_name`, `email`, and product `role` only after an authorized 200.
- Customer onboarding and mobile !thute Auth OIDC/PKCE are **not** implemented.
- In particular, this does **not** make existing merchant portal login a customer login.
- Cookies scoped only to `portal.pay.ithute.co.ls` will not authenticate `pay.ithute.co.ls`.
  Do not expand the cookie domain or bypass HttpOnly/SameSite protections as a shortcut.
- Native Android/iOS authentication is not yet available; app-specific OIDC redirect
  registration and system-browser PKCE will require a dedicated security review.

### Staging checks

Build with `docker build -t ithutepay-flutter-web:phase3 .` (runs Flutter
unit tests), then deploy the image **only to a temporary container** before
updating the production app. Check:

```bash
# From a machine with access to the standalone staging container:
docker exec ithutepay-flutter-stage3 wget -q -O - http://127.0.0.1/healthz
docker exec ithutepay-flutter-stage3 wget -q -O - http://127.0.0.1/service-health
# EXPECTED without valid cookies: HTTP 401/403, not 200 or an HTML SPA response.
docker exec ithutepay-flutter-stage3 wget -S -O /dev/null http://127.0.0.1/mobile-session
```

If an unauthenticated request to `/mobile-session` receives 200 or reveals a
profile, **do not deploy**. Full authenticated browser testing should occur
before exposing account details in production.
