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
