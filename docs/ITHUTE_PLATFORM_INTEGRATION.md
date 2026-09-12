# Ithute Pay: !thute Auth and !thute Push integration

Ithute Pay is a first-party product client. Central services provide identity and notification transport only; Ithute Pay keeps its payment and authorization data in its own database.

## Identity boundary

Client ID: `ithute-pay`

Ithute Pay accepts RS256 access tokens only when all of the following are true:

- `iss` is the configured `https://auth.ithute.co.ls` issuer;
- `aud` is exactly `ithute-pay`;
- `token_use` is `access`;
- signature validation succeeds against central JWKS;
- `sub` and `sid` are UUIDs;
- the token is not expired; and
- the immutable central `sub` is already linked to an active local Ithute Pay user through `users.auth_user_id`.

The product does not merge users by email or phone. Existing users first sign in with the migration login and select **Link !thute account** from Platform settings. The browser is redirected to central Auth using Authorization Code + PKCE. The callback verifies `state`, ID-token `nonce`, issuer, audience, signature and the matching access/ID-token subject before writing the link.

After linking, **Continue with !thute** becomes the normal sign-in path. Product roles remain local.

## Safe migration sequence

1. Deploy the migration adding nullable unique `users.auth_user_id`.
2. Add `ithute-pay:Ithute Pay` to central Auth first-party clients.
3. Add the exact callback URL to `AUTH_REDIRECT_URIS_JSON`. Production must use HTTPS.
4. Set `ITHUTE_AUTH_ENABLED=true` on Ithute Pay while keeping `ITHUTE_AUTH_LEGACY_LOGIN_ENABLED=true`.
5. Have required administrators link their central identities from Platform settings.
6. Confirm central login, local role enforcement, session refresh and logout.
7. Only after migration is complete, set `ITHUTE_AUTH_LEGACY_LOGIN_ENABLED=false` and optionally disable automatic local-admin bootstrap according to the operations plan.

Do not remove local password hashes or rows as part of the initial rollout. Account unlinking/recovery should be an audited operations procedure rather than an email-based merge.

## Push boundary

Ithute Pay never stores FCM, APNs or Web-Push provider credentials.

A signed-in central user can register a device through the Ithute Pay proxy endpoints:

- `POST /api/v1/notifications/devices`
- `GET /api/v1/notifications/devices`
- `DELETE /api/v1/notifications/devices/{device_key}`

The product forwards the verified `ithute-pay` user access token to `!thute Push`, which binds the provider endpoint to the central `sub` and product client ID.

Server-generated notifications use this trust chain:

```text
Ithute Pay backend
  -> POST auth.ithute.co.ls/v1/auth/service-token
     client_id=ithute-pay
     audience=ithute-push
     scope=push.send
  -> POST !thute Push /v1/messages
     recipient_sub=<central UUID>
```

The shared service secret exists only at runtime in both central Auth's `AUTH_SERVICE_CLIENT_SECRETS_JSON` and Ithute Pay's `ITHUTE_PUSH_SERVICE_CLIENT_SECRET`. It must be unique, random, at least 24 characters, and never committed.

`POST /api/v1/notifications/test` queues a self-notification for the currently linked user and is intended for rollout verification.

## Production values that must be set

Ithute Pay:

```text
ITHUTE_AUTH_ENABLED=true
ITHUTE_AUTH_LEGACY_LOGIN_ENABLED=true
ITHUTE_AUTH_ISSUER=https://auth.ithute.co.ls
ITHUTE_AUTH_AUDIENCE=ithute-pay
ITHUTE_AUTH_REDIRECT_URI=https://<ithute-pay-host>/api/v1/auth/ithute/callback
ITHUTE_PUSH_ENABLED=true
ITHUTE_PUSH_URL=https://<push-host>
ITHUTE_PUSH_SERVICE_CLIENT_SECRET=<runtime secret>
```

Central Auth must include the matching client, exact callback URL and matching service secret. Central Push must include `ithute-pay` in both its user-client and service-client allowlists.

## Failure behavior

- If central Auth JWKS or token exchange is unavailable, central login fails closed. Legacy login remains available only while the migration flag is enabled.
- If Push is unavailable, payment processing is not failed or rolled back. Notification endpoints return a service-unavailable response and can be retried independently.
- Merchant API keys remain a separate machine-to-machine mechanism and are not replaced by human SSO.
