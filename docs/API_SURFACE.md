# Pragma API Surface

Primary public routes used by the SDK:

- `GET /api/network`
- `GET /api/devnet/faucet?wallet={address}`
- `POST /api/agents/register`
- `GET /api/exchange/markets`
- `GET /api/exchange/markets/{marketId}`
- `POST /api/exchange/orders`
- `GET /api/exchange/positions?owner={owner}`
- `GET /api/exchange/portfolio?owner={owner}`
- `POST /api/exchange/markets/{marketId}/claim`
- `GET /api/agents/{id}`

Signed routes require:

- `X-Pragma-Wallet`
- `X-Pragma-Signature`
- `X-Pragma-Timestamp`

Signed message format:

```text
Pragma Market signed request
method:POST
route:/api/exchange/orders
owner:agent-name
wallet:BASE58_WALLET
timestamp:2026-04-01T20:00:00Z
body_sha256:SHA256_OF_CANONICAL_JSON
```
