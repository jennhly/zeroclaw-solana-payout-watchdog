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

## Still required before bounty submission

- Run on a genuine ZeroClaw channel using a user-controlled public wallet and
  trusted HTTPS RPC.
- Capture the channel interaction. A “no new finalized credits” response is
  honest evidence; a credit may be called real only when the result is
  `mode=live`, `commitment=finalized`, and includes an independently verifiable
  Explorer URL.
- Publish the repository, add the real URLs to `SHOWCASE_DRAFT.md`, post the
  showcase in the required Discord channel, and submit the Superteam form.

