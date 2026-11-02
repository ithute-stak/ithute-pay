# IthutePay production Caddy routing and health checks

## Incident (2026-11-02)

After a VPS upgrade, `portal.pay.ithute.co.ls` and `api.pay.ithute.co.ls` returned HTTP 502.
Caddy on Docker network `public-edge` had IP `172.20.0.9`, yet both routes were
pointed to `172.20.0.9:3001` and `172.20.0.9:8001`. IthutePay was actually
`172.20.0.8`. Reloading Caddy did not correct its upstreams until the product
route file was edited. The repaired hostnames resolved and the portal returned 307
and API 200.

## Durable deployment rule

- Keep the current production file at the Caddy persistent-volume location,
  `/var/lib/docker/volumes/ithute_ithute_caddy_data/_data/product-routes/ithutepay.caddy`.
  Main Caddyfile imports `/data/product-routes/*.caddy`.
- Preserve any existing security headers, TLS policies and additional handlers. Replace
  **only** the targets of the two `reverse_proxy` directives with the stable Docker name
  `ithute-pay-ithute-pay-bridge-1:3001` and `ithute-pay-ithute-pay-bridge-1:8001`.
  See `deploy/caddy/ithutepay.routes.caddy.example` for minimal reference routing.
- Ensure both Caddy and IthutePay attach to the `public-edge` network, and verify
  the service alias resolves inside Caddy. Do **not** use container IPs, `localhost`,
  `host.docker.internal` or the host's public IP as the Docker upstream.
- Update the production provisioning/deployment automation that **writes** the route
  file, otherwise it may overwrite the repaired routes on the next deploy.
  The generator lives outside this repository and must be audited separately.
- Do not stop or recreate Postgres/Redis to correct a proxy error.

## Safe deployment procedure

1. Back up the *existing* route and inspect it for non-IthutePay domains and headers.
2. Verify reachability from the proxy:
   `docker exec ithute-caddy-1 wget -S -O /dev/null http://ithute-pay-ithute-pay-bridge-1:3001/`
   and similarly port 8001 (direct API root may return a host validation error without the public Host header).
3. Edit only IthutePay's upstreams in the persistent route file.
4. `docker exec ithute-caddy-1 caddy validate --config /etc/caddy/Caddyfile`
5. Only after successful validation:
   `docker exec ithute-caddy-1 caddy reload --config /etc/caddy/Caddyfile`
6. Run `bash deploy/vps/check-public-routes.sh`. Inspect browser login and authenticated API flows separately.

## Monitoring

Run `bash deploy/vps/check-public-routes.sh` from a trusted external monitoring host
to detect public 502/503/504 errors. The script exits nonzero on failures, which
can trigger an existing alerting service or scheduled job. It does **not** create a
notification delivery channel by itself. Prefer an authenticated health endpoint
for deeper checks; the two public smoke checks prove routing, not payment settlement.

## Payment safety

Keep direct M-Pesa integrations and optional Golink providers unchanged. No payment
credentials, merchant data, database volumes or payment state should be changed by a routing repair.
