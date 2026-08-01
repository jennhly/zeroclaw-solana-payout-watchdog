# Discord showcase draft — ready for review before posting

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

Verification: https://github.com/jennhly/zeroclaw-solana-payout-watchdog/blob/main/VERIFICATION.md

Live demo result: ZeroClaw 0.8.3 accepted an HMAC-signed webhook, invoked the
installed skill, queried Solana mainnet over HTTPS with finalized commitment,
and correctly reported no new USDG/USDC credits. The public wallet is redacted
in the write-up; no keys were used. This is channel-and-chain evidence, not a
claim that a payout occurred.

Discord showcase URL: `[ADD AFTER POSTING]`

Reproduce: Python 3.11+, copy the config, provide a public address, run the
documented validation and tests, then install the directory as a ZeroClaw
skill bundle.
