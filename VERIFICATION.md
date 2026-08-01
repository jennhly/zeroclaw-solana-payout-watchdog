# Verification record

Date: 2026-07-31

## Deterministic checks

- Python: 3.13.0 (the package requires 3.11 or newer)
- Unit tests: 5 passed
- Full parent money-engine suite: 115 passed
- Packaging: isolated virtual environment install succeeded and exposed the
  `solana-payout-watchdog` console command
- ZeroClaw: official `zeroclaw 0.8.3` arm64 macOS release; SHA-256 matched the
  release checksum
- `zeroclaw skills audit .`: passed, 18 source files scanned
- Bundle install: succeeded; ZeroClaw listed one loaded skill and its
  `check_payouts` tool

## End-to-end ZeroClaw agent check

The official ZeroClaw CLI agent ran against a local OpenAI-compatible model
stub and a local Solana JSON-RPC stub. The model called:

```text
solana-payout-watchdog__check_payouts {}
```

The tool returned one 2.5 USDG test credit with:

```json
{
  "commitment": "finalized",
  "mode": "local-rpc",
  "source": "local-rpc"
}
```

It deliberately emitted no Explorer URL. The agent's final response was:

```text
Integration demo complete. The result is local-rpc test data, not a real payout.
```

This proves the agent-to-skill-to-RPC-to-agent loop without pretending a mock
credit is on-chain payment evidence.

## Signed webhook + live mainnet check

At 2026-07-31 20:19 EDT, the official ZeroClaw 0.8.3 daemon accepted an
HMAC-SHA256-signed request on its webhook channel and returned HTTP 200. The
agent used the installed `solana-payout-watchdog__check_payouts` tool against
an HTTPS Solana mainnet RPC for the user-controlled public wallet
`B4NX…umDS`. The wallet is intentionally redacted here; no private or signing
material was requested or used.

The tool receipt was:

```json
{
  "alerts": [],
  "bootstrapped_accounts": 0,
  "commitment": "finalized",
  "mode": "live",
  "scanned_signatures": 0,
  "status": "ok",
  "token_accounts": 0,
  "wallet": "B4NX…umDS"
}
```

ZeroClaw delivered this reply to the configured callback:

```text
Live finalized Solana scan complete. No new USDG or USDC payout credits were found for the configured public wallet.
```

The channel, agent loop, skill process, and callback ran locally; a deterministic
OpenAI-compatible model adapter selected the only allowlisted tool. The chain
query itself was live, not stubbed. This result proves the signed-channel flow
and a successful finalized mainnet read. It does **not** claim that a payout was
received. There is no Explorer URL because there was no credit alert.

## Still required before bounty submission

- Capture a short screen recording or screenshots of the reproducible demo if
  the submission form requires media.
- Post `SHOWCASE_DRAFT.md` in the required ZeroClaw Discord channel and add the
  resulting message URL to the draft.
- Submit the final repository and showcase URLs through the Superteam form.
