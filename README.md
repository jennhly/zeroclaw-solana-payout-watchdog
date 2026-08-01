# ZeroClaw Solana Payout Watchdog

A read-only ZeroClaw skill that checks a public Solana wallet for new,
finalized USDG or USDC credits. It gives bounty workers one concise answer to
“did I actually get paid?” without ever loading a key or constructing a
transaction.

## Why this is a real agent job

The stock ZeroClaw agent receives a message through a configured channel,
calls the narrow `solana-payout-watchdog__check_payouts` tool, and explains only
the newly finalized credits. The deterministic tool handles chain accounting;
the agent handles the human-facing response. Run it from ZeroClaw's signed
webhook channel for integrations, or from its CLI while developing.

The skill is intentionally Tier 0/read-only:

- Solana-native RPC reads and SPL-token balance reconciliation
- no seed phrase, private key, keypair, signing key, or transaction approval
- no transaction construction, simulation, signing, or submission code
- finalized commitment and an independent Explorer link for live alerts
- atomic local state so repeated checks do not announce the same credit twice
- fixture output that cannot be confused with a real payout

## Reproduce the deterministic demo

Python 3.11 or newer is the only runtime dependency.

```bash
mkdir -p .demo
python3 payout_watchdog.py validate --config fixtures/watchdog.fixture.toml
python3 payout_watchdog.py scan \
  --config fixtures/watchdog.fixture.toml \
  --fixture fixtures/rpc-sequence.json \
  --state .demo/state.json
python3 -m unittest discover -s tests -v
```

The scan reports one fixture-labeled 2.5 USDG credit. Run the same scan again
and it reports no alerts, demonstrating idempotence. It is test data, not
payment proof.

## Run against Solana mainnet

1. Copy `watchdog.example.toml` to `watchdog.toml`.
2. Replace `wallet` with a public Solana address. Do not supply any secret.
3. Validate, then run the first scan:

```bash
python3 payout_watchdog.py validate --config watchdog.toml
python3 payout_watchdog.py scan --config watchdog.toml
```

`bootstrap = true` makes the first scan establish a baseline without calling
old transfers new payouts. Later finalized credits are emitted once. Lower the
per-token `minimum_amount` only if small-payment alerts are useful.

The included mainnet mints are the issuer-documented addresses:

- USDG: `2u1tszSeqZ3qBWF3uNGPFc8TzMk2tdiwknnRMWGWjGWH`
- USDC: `EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v`

## Install into ZeroClaw

First install the zero-dependency CLI into an executable directory on the
`PATH` used by ZeroClaw. For example, with `pipx`:

```bash
pipx install .
solana-payout-watchdog --help
```

Then install the directory into a bundle named `solana`:

```bash
zeroclaw skills bundle add solana
zeroclaw skills install . --bundle solana
zeroclaw skills audit shared/skills/solana/zeroclaw-solana-payout-watchdog
zeroclaw skills test --verbose
```

Copy `watchdog.example.toml` to `payout-watchdog.toml` in the target agent's
workspace (`<install>/agents/payout_watchdog/workspace/` in the provided
config snippet), then replace the public wallet. Keeping the CLI on `PATH` and
the config in the agent workspace avoids brittle bundle-relative paths. The
skill command is static and accepts no model-controlled shell arguments.

Add the `solana` bundle to the target agent. The provided narrow risk profile
auto-approves only this static, read-only skill tool; the webhook channel also
hides generic shell, file-write, HTTP, browser, and cron tools.

`docs/zeroclaw-config-snippet.toml` shows the narrow bundle, agent, and local
webhook wiring. Merge it into an existing ZeroClaw config and replace the model
provider and secret placeholders. The example channel stays disabled until
those values are deliberately configured.

For a local webhook channel, configure a strong secret and send signed JSON as
documented by ZeroClaw. Never expose an unauthenticated webhook. A real demo
must show the channel message, the tool receipt, and either “no new finalized
credits” or a live alert whose Explorer transaction is independently visible.

For a fully reproducible signed-channel run, install the official ZeroClaw
binary, create the ignored `payout-watchdog.toml`, and run:

```bash
python3 demo/live_webhook_demo.py --zeroclaw /path/to/zeroclaw
```

The script creates an isolated runtime, installs and audits this skill, starts
an HMAC-authenticated webhook, and performs a live scan using the operator's
HTTPS RPC configuration. Its deterministic local model adapter needs no API
key and can only select the one allowlisted read-only tool. Wallet output is
redacted.

## Output contract

The command prints one JSON object. `mode=live` means it contacted a non-local
HTTPS RPC. A real-credit alert additionally has `commitment=finalized` and
`explorer_url`. `mode=fixture` is reproducible test data and `mode=local-rpc`
is a loopback integration test; neither is proof of payment.

See [THREAT_MODEL.md](THREAT_MODEL.md) for RPC trust, privacy, and non-goals.
See [VERIFICATION.md](VERIFICATION.md) for the tested ZeroClaw version, local
stub receipt, and HMAC-signed webhook flow with a live finalized mainnet read.

## References

- [ZeroClaw repository](https://github.com/zeroclaw-labs/zeroclaw)
- [Superteam ZeroClaw bounty](https://superteam.fun/earn/listing/zeroclaw)
- [Paxos USDG addresses](https://docs.paxos.com/guides/stablecoin/usdg/mainnet)
- [Circle USDC addresses](https://developers.circle.com/stablecoins/usdc-contract-addresses)

## License

MIT
