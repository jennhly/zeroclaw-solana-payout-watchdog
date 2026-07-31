#!/usr/bin/env python3
"""Read-only, finalized Solana stablecoin payout monitor for ZeroClaw.

The program has no transaction construction, signing, keypair, or sendTransaction
code. It uses three read-only JSON-RPC methods and emits a single JSON document.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Protocol


MAX_RESPONSE_BYTES = 10 * 1024 * 1024
BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
BASE58_VALUES = {char: index for index, char in enumerate(BASE58_ALPHABET)}
READ_ONLY_METHODS = {
    "getTokenAccountsByOwner",
    "getSignaturesForAddress",
    "getTransaction",
}


class WatchdogError(Exception):
    """Expected configuration, fixture, or RPC failure."""


@dataclass(frozen=True)
class TokenConfig:
    symbol: str
    mint: str
    decimals: int
    minimum_units: int


@dataclass(frozen=True)
class Config:
    rpc_url: str
    wallet: str
    state_path: Path
    bootstrap: bool
    max_signatures: int
    tokens: tuple[TokenConfig, ...]


class Rpc(Protocol):
    source: str

    def call(self, method: str, params: list[Any]) -> Any: ...


def _base58_decoded_length(value: str) -> int:
    if not value or any(char not in BASE58_VALUES for char in value):
        return -1
    number = 0
    for char in value:
        number = number * 58 + BASE58_VALUES[char]
    payload_length = (number.bit_length() + 7) // 8 if number else 0
    leading_zeroes = len(value) - len(value.lstrip("1"))
    return leading_zeroes + payload_length


def validate_pubkey(value: str, label: str) -> str:
    if _base58_decoded_length(value) != 32:
        raise WatchdogError(f"{label} must be a base58-encoded 32-byte Solana public key")
    return value


def _amount_to_units(value: object, decimals: int, label: str) -> int:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise WatchdogError(f"{label} must be a decimal number") from exc
    if not amount.is_finite() or amount < 0:
        raise WatchdogError(f"{label} must be a finite non-negative number")
    scaled = amount * (10**decimals)
    if scaled != scaled.to_integral_value():
        raise WatchdogError(f"{label} has more than {decimals} decimal places")
    return int(scaled)


def _safe_rpc_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    local_hosts = {"127.0.0.1", "localhost", "::1"}
    if parsed.scheme == "https" and parsed.hostname:
        return value
    if parsed.scheme == "http" and parsed.hostname in local_hosts:
        return value
    raise WatchdogError("rpc_url must use HTTPS, except loopback HTTP used for local testing")


def load_config(path: Path, state_override: Path | None = None) -> Config:
    try:
        with path.open("rb") as handle:
            raw = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise WatchdogError(f"could not load config: {exc}") from exc

    wallet = validate_pubkey(str(raw.get("wallet", "")), "wallet")
    rpc_url = _safe_rpc_url(str(raw.get("rpc_url", "")))
    bootstrap = bool(raw.get("bootstrap", True))
    max_signatures = raw.get("max_signatures", 25)
    if not isinstance(max_signatures, int) or not 1 <= max_signatures <= 100:
        raise WatchdogError("max_signatures must be an integer from 1 through 100")

    raw_tokens = raw.get("tokens")
    if not isinstance(raw_tokens, list) or not raw_tokens:
        raise WatchdogError("config must contain at least one [[tokens]] entry")
    tokens: list[TokenConfig] = []
    seen_mints: set[str] = set()
    for index, item in enumerate(raw_tokens):
        if not isinstance(item, dict):
            raise WatchdogError(f"tokens[{index}] must be a table")
        symbol = str(item.get("symbol", "")).strip().upper()
        if not symbol or len(symbol) > 16 or not symbol.replace("-", "").isalnum():
            raise WatchdogError(f"tokens[{index}].symbol is invalid")
        mint = validate_pubkey(str(item.get("mint", "")), f"tokens[{index}].mint")
        if mint in seen_mints:
            raise WatchdogError(f"duplicate token mint: {mint}")
        decimals = item.get("decimals")
        if not isinstance(decimals, int) or not 0 <= decimals <= 18:
            raise WatchdogError(f"tokens[{index}].decimals must be an integer from 0 through 18")
        minimum_units = _amount_to_units(
            item.get("minimum_amount", "0"), decimals, f"tokens[{index}].minimum_amount"
        )
        tokens.append(TokenConfig(symbol, mint, decimals, minimum_units))
        seen_mints.add(mint)

    configured_state = Path(str(raw.get("state_path", "watchdog-state.json")))
    if state_override is not None:
        state_path = state_override if state_override.is_absolute() else Path.cwd() / state_override
    else:
        state_path = configured_state
        if not state_path.is_absolute():
            state_path = path.parent / state_path
    return Config(rpc_url, wallet, state_path.resolve(), bootstrap, max_signatures, tuple(tokens))


class LiveRpc:
    def __init__(self, url: str, timeout_seconds: int = 20):
        self.url = url
        self.timeout_seconds = timeout_seconds
        self.request_id = 0
        hostname = urllib.parse.urlsplit(url).hostname
        self.source = "local-rpc" if hostname in {"127.0.0.1", "localhost", "::1"} else "live"

    def call(self, method: str, params: list[Any]) -> Any:
        if method not in READ_ONLY_METHODS:
            raise WatchdogError(f"RPC method is not allowlisted: {method}")
        self.request_id += 1
        body = json.dumps(
            {"jsonrpc": "2.0", "id": self.request_id, "method": method, "params": params},
            separators=(",", ":"),
        ).encode()
        request = urllib.request.Request(
            self.url,
            data=body,
            headers={"Content-Type": "application/json", "User-Agent": "zeroclaw-payout-watchdog/0.1"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = response.read(MAX_RESPONSE_BYTES + 1)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise WatchdogError(f"Solana RPC request failed for {method}: {exc}") from exc
        if len(payload) > MAX_RESPONSE_BYTES:
            raise WatchdogError("Solana RPC response exceeded 10 MiB safety limit")
        try:
            decoded = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WatchdogError("Solana RPC returned invalid JSON") from exc
        if not isinstance(decoded, dict) or decoded.get("jsonrpc") != "2.0":
            raise WatchdogError("Solana RPC returned an invalid envelope")
        if decoded.get("error") is not None:
            error = decoded["error"]
            code = error.get("code") if isinstance(error, dict) else "unknown"
            raise WatchdogError(f"Solana RPC returned error code {code} for {method}")
        return decoded.get("result")


class FixtureRpc:
    source = "fixture"

    def __init__(self, path: Path):
        try:
            raw = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise WatchdogError(f"could not load fixture: {exc}") from exc
        calls = raw.get("calls") if isinstance(raw, dict) else None
        if not isinstance(calls, list):
            raise WatchdogError("fixture must contain a calls array")
        self.calls = calls
        self.index = 0

    def call(self, method: str, params: list[Any]) -> Any:
        if method not in READ_ONLY_METHODS:
            raise WatchdogError(f"fixture method is not allowlisted: {method}")
        if self.index >= len(self.calls):
            raise WatchdogError(f"fixture has no response for {method}")
        expected = self.calls[self.index]
        self.index += 1
        if not isinstance(expected, dict) or expected.get("method") != method:
            actual = expected.get("method") if isinstance(expected, dict) else None
            raise WatchdogError(f"fixture expected {actual!r}, scanner called {method!r}")
        expected_first = expected.get("first_param")
        if expected_first is not None and (not params or params[0] != expected_first):
            raise WatchdogError(f"fixture first parameter mismatch for {method}")
        return expected.get("result")


def _load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "seen": {}}
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise WatchdogError(f"could not load state: {exc}") from exc
    if not isinstance(value, dict) or value.get("version") != 1 or not isinstance(value.get("seen"), dict):
        raise WatchdogError("state file has an unsupported or invalid format")
    return value


def _save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False) as handle:
            temporary_name = handle.name
            json.dump(state, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, path)
    except OSError as exc:
        if temporary_name:
            try:
                os.unlink(temporary_name)
            except OSError:
                pass
        raise WatchdogError(f"could not save state: {exc}") from exc


def _account_keys(transaction: dict[str, Any]) -> list[str]:
    message = transaction.get("transaction", {}).get("message", {})
    raw_keys = message.get("accountKeys", []) if isinstance(message, dict) else []
    keys = [item.get("pubkey", "") if isinstance(item, dict) else str(item) for item in raw_keys]
    loaded = transaction.get("meta", {}).get("loadedAddresses", {})
    if isinstance(loaded, dict):
        keys.extend(str(item) for item in loaded.get("writable", []))
        keys.extend(str(item) for item in loaded.get("readonly", []))
    return keys


def _balance_units(items: object, account_index: int, mint: str) -> tuple[int, int] | None:
    if not isinstance(items, list):
        return None
    for item in items:
        if not isinstance(item, dict) or item.get("accountIndex") != account_index or item.get("mint") != mint:
            continue
        amount = item.get("uiTokenAmount", {}).get("amount")
        decimals = item.get("uiTokenAmount", {}).get("decimals")
        try:
            return int(str(amount)), int(decimals)
        except (TypeError, ValueError):
            return None
    return None


def detect_credit(
    transaction: dict[str, Any], token_account: str, token: TokenConfig
) -> int:
    meta = transaction.get("meta")
    if not isinstance(meta, dict) or meta.get("err") is not None:
        return 0
    keys = _account_keys(transaction)
    try:
        account_index = keys.index(token_account)
    except ValueError:
        return 0
    pre = _balance_units(meta.get("preTokenBalances"), account_index, token.mint)
    post = _balance_units(meta.get("postTokenBalances"), account_index, token.mint)
    pre_units, pre_decimals = pre or (0, token.decimals)
    post_units, post_decimals = post or (0, token.decimals)
    if pre_decimals != token.decimals or post_decimals != token.decimals:
        raise WatchdogError(f"RPC decimals for {token.symbol} do not match the configured value")
    return max(0, post_units - pre_units)


def _format_units(units: int, decimals: int) -> str:
    if decimals == 0:
        return str(units)
    raw = str(units).rjust(decimals + 1, "0")
    value = f"{raw[:-decimals]}.{raw[-decimals:]}".rstrip("0").rstrip(".")
    return value or "0"


def _explorer_url(signature: str, rpc_url: str) -> str:
    lowered = rpc_url.lower()
    suffix = "?cluster=devnet" if "devnet" in lowered else ""
    return f"https://explorer.solana.com/tx/{signature}{suffix}"


def scan(config: Config, rpc: Rpc) -> dict[str, Any]:
    state = _load_state(config.state_path)
    seen_state: dict[str, list[str]] = state["seen"]
    alerts: list[dict[str, Any]] = []
    scanned_signatures = 0
    token_accounts_count = 0
    bootstrapped_accounts = 0

    for token in config.tokens:
        accounts_result = rpc.call(
            "getTokenAccountsByOwner",
            [
                config.wallet,
                {"mint": token.mint},
                {"encoding": "jsonParsed", "commitment": "finalized"},
            ],
        )
        values = accounts_result.get("value", []) if isinstance(accounts_result, dict) else []
        for account in values:
            token_account = account.get("pubkey") if isinstance(account, dict) else None
            if not isinstance(token_account, str):
                continue
            validate_pubkey(token_account, "RPC token account")
            token_accounts_count += 1
            state_key = f"{config.wallet}:{token.mint}:{token_account}"
            already_seen = list(seen_state.get(state_key, []))
            seen_set = set(already_seen)
            signatures_result = rpc.call(
                "getSignaturesForAddress",
                [token_account, {"limit": config.max_signatures, "commitment": "finalized"}],
            )
            signatures = signatures_result if isinstance(signatures_result, list) else []
            valid_entries = [item for item in signatures if isinstance(item, dict) and isinstance(item.get("signature"), str)]
            unseen = [item for item in valid_entries if item["signature"] not in seen_set]
            scanned_signatures += len(unseen)

            if not already_seen and config.bootstrap:
                already_seen.extend(item["signature"] for item in valid_entries)
                seen_state[state_key] = already_seen[-500:]
                bootstrapped_accounts += 1
                continue

            for entry in reversed(unseen):
                signature = entry["signature"]
                if entry.get("err") is not None:
                    already_seen.append(signature)
                    continue
                transaction = rpc.call(
                    "getTransaction",
                    [
                        signature,
                        {
                            "encoding": "jsonParsed",
                            "commitment": "finalized",
                            "maxSupportedTransactionVersion": 0,
                        },
                    ],
                )
                if not isinstance(transaction, dict):
                    continue
                credit_units = detect_credit(transaction, token_account, token)
                if credit_units >= token.minimum_units and credit_units > 0:
                    block_time = transaction.get("blockTime")
                    observed_at = None
                    if isinstance(block_time, int):
                        observed_at = datetime.fromtimestamp(block_time, timezone.utc).isoformat()
                    alert = {
                        "amount": _format_units(credit_units, token.decimals),
                        "asset": token.symbol,
                        "block_time": observed_at,
                        "commitment": "finalized",
                        "mint": token.mint,
                        "signature": signature,
                        "slot": transaction.get("slot"),
                        "source": rpc.source,
                        "token_account": token_account,
                        "wallet": config.wallet,
                    }
                    if rpc.source == "live":
                        alert["explorer_url"] = _explorer_url(signature, config.rpc_url)
                    alerts.append(alert)
                already_seen.append(signature)
            seen_state[state_key] = already_seen[-500:]

    _save_state(config.state_path, state)
    return {
        "alerts": alerts,
        "bootstrapped_accounts": bootstrapped_accounts,
        "commitment": "finalized",
        "mode": rpc.source,
        "scanned_signatures": scanned_signatures,
        "status": "ok",
        "token_accounts": token_accounts_count,
        "wallet": config.wallet,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only finalized Solana payout watchdog")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate_parser = subparsers.add_parser("validate", help="validate configuration without network access")
    validate_parser.add_argument("--config", required=True, type=Path)
    scan_parser = subparsers.add_parser("scan", help="scan for new finalized stablecoin credits")
    scan_parser.add_argument("--config", required=True, type=Path)
    scan_parser.add_argument("--fixture", type=Path, help="replay labeled test data instead of using the network")
    scan_parser.add_argument("--state", type=Path, help="override state path (useful for reproducible demos)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        state_override = getattr(args, "state", None)
        config = load_config(args.config.resolve(), state_override)
        if args.command == "validate":
            print(json.dumps({"status": "ok", "tokens": [token.symbol for token in config.tokens], "wallet": config.wallet}))
            return 0
        rpc: Rpc = FixtureRpc(args.fixture.resolve()) if args.fixture else LiveRpc(config.rpc_url)
        print(json.dumps(scan(config, rpc), sort_keys=True))
        return 0
    except WatchdogError as exc:
        print(json.dumps({"status": "error", "error": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
