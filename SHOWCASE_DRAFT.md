# Discord showcase draft — do not post until the demo is real

**Bounty Payout Watchdog — a Tier 0 read-only Solana job for ZeroClaw**

This agent checks a configured public Solana wallet for newly finalized USDG
or USDC credits, deduplicates them, and replies on a real ZeroClaw channel. The
chain reconciliation is deterministic; ZeroClaw turns the result into a short
human-facing payout status.

Safety boundary: public addresses only, three allowlisted read-only RPC
methods, finalized commitment, issuer-verified mint allowlist, no key material,
and no transaction code. Fixture demos are unmistakably labeled and cannot be
used as fake payment proof.

Repository: https://github.com/jennhly/zeroclaw-solana-payout-watchdog

Demo: `[ADD REAL CHANNEL DEMO URL]`

Reproduce: Python 3.11+, copy the config, provide a public address, run the
documented validation and tests, then install the directory as a ZeroClaw
skill bundle.
