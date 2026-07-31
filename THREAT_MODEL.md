# Threat model

## Security boundary

The watchdog accepts a public Solana address, an HTTPS RPC endpoint, and an
allowlist of token mints. It never accepts or loads seed phrases, private keys,
keypairs, signing keys, or transaction bytes.

The network allowlist contains only these read-only Solana JSON-RPC methods:

- `getTokenAccountsByOwner`
- `getSignaturesForAddress`
- `getTransaction`

There is no transaction builder and no call to `sendTransaction` or
`simulateTransaction`. The only write is an atomic, mode-`0600` local state
file used to suppress duplicate alerts.

## Trust assumptions

- A configured RPC can omit or lie about chain data. Operators should use a
  trusted endpoint; each real alert includes a Solana Explorer link for an
  independent check.
- An allowlisted mint can still be configured incorrectly. The included USDG
  and USDC mints come from Paxos and Circle documentation, respectively.
- `finalized` commitment reduces rollback risk but does not prove the off-chain
  business reason for a transfer. The alert says a token credit occurred; a
  human or accounting system still matches it to a bounty.
- A public wallet address is not a secret, but the state file can reveal
  payment timing. It is written with owner-only permissions.

## Fixture isolation

Fixture mode is deliberately explicit. Its output says `mode=fixture`, each
alert says `source=fixture`, and fixture alerts have no explorer link. A
loopback endpoint similarly reports `mode=local-rpc` and omits Explorer links.
This prevents a fixture or local mock demo from being presented as proof of a
real payout.

## Non-goals

- Sending, signing, preparing, or simulating transactions
- Holding funds or keys
- Proving a token credit corresponds to a specific bounty without external
  reconciliation
- Indexing closed token accounts or history older than the configured recent
  signature window
