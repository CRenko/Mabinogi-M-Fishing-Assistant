# Remote protocol v1

Base URL: HTTPS origin only. No credentials in URLs; clients do not follow redirects. Requests and responses use JSON. Requests are capped at 4 KiB; status contains no raw logs or images. Every response has `Cache-Control: no-store`. No cross-origin browser API / CORS is exposed by this native-client service.

| Endpoint | Authorization | Purpose |
| --- | --- | --- |
| GET /v1/info | none | Protocol version, service name, reporting interval |
| POST /v1/activate | one-time code in body | Redeem code with a client-generated 64-character hex `write_token` |
| PUT /v1/status | Bearer write token | Replace latest status, at least 55 seconds between accepted writes |
| GET /v1/status | Bearer read token | Only the token's own device; includes server time, receipt time and stale flag |
| POST /v1/pair | Bearer write token | Revoke old reader and generate new 48-character hex pairing code, valid 600 seconds |
| POST /v1/pair/claim | pair code in body | Claim with client-generated 64-character hex `read_token` |
| POST /v1/unpair | Bearer write token | Revoke phone access and pairing code |
| POST /admin/codes | Bearer ADMIN_TOKEN | `{count:1..25, days:1..365}`; return activation codes once |
| GET /admin/devices | Bearer ADMIN_TOKEN | Device IDs, registration time, last receipt and revocation flag, no tokens |
| DELETE /admin/devices/{id} | Bearer ADMIN_TOKEN | Revoke computer and phone, discard its current status |

Activation request: `{ "code": "...", "write_token": "..." }`.
Response: `{ "device_id": "UUID", "interval_seconds": 60 }`.

Pair claim request: `{ "pair_code": "...", "read_token": "..." }`.
Response: `{ "device_id": "UUID", "interval_seconds": 60 }`.
Repeating activation/claim with the same token is idempotent while valid. Another token cannot reuse the same code. Capacity enforcement and redemption happen in one SQLite statement. A new phone pairing is explicit and invalidates the old read token.

QR format: `okfishing://pair?v=1&relay=<URL-encoded HTTPS origin>&code=<48 lowercase hex characters>`.
Never put the admin secret, activation code or write token in this QR. The phone must validate and display the relay address before connecting. “Remember this device” controls encrypted local persistence; it does not grant additional server permissions.

Status allowlist:

```json
{
  "monitoring": true,
  "calibrated": true,
  "state": "waiting_bite",
  "strategy": "fixed_delay",
  "recognition": "ok",
  "reason": "",
  "version": "0.6.4",
  "observed_at": 1788800000
}
```

States: `idle`, `paused`, `running`, `waiting_bite`, `ready_to_cast`, `fish_hooked`, `idle_recovery`, `cleaning`, `stopped`, `unresponsive`.
Strategies: `stamina_bounce`, `fixed_delay`, `instant`. Recognition: `ok`, `pixel`.
Reasons: empty, `manual`, `inventory_full`, `rod_required`, `retry_limit`, `error`.
`observed_at` is a desktop event timestamp, not proof that the image is fresh. `unresponsive` means the desktop has not observed engine events for 30 seconds while monitoring.

Status response: `{ device_id, server_time, received_at, stale, status }`.
`status` is null before the first report. `stale` is true after 180 seconds without a report. The mobile client also ages its cached response using a monotonic clock and shows connection failures separately.

Errors: `{ "error": "machine_code", "message": "safe display message" }` with HTTP 400/401/403/409/413/415/429/503. Retry networking at most once a minute. Do not log request bodies or Authorization. Free-tier exhaustion is a remote-view failure, never a command to stop local automation.
