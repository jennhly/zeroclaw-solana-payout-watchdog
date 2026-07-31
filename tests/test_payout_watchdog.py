from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import payout_watchdog as watchdog


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_CONFIG = ROOT / "fixtures" / "watchdog.fixture.toml"
FIXTURE_RPC = ROOT / "fixtures" / "rpc-sequence.json"


class PayoutWatchdogTests(unittest.TestCase):
    def test_known_public_keys_decode_to_32_bytes(self) -> None:
        self.assertEqual(
            watchdog.validate_pubkey("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", "mint"),
            "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        )
        with self.assertRaises(watchdog.WatchdogError):
            watchdog.validate_pubkey("not-a-solana-address", "wallet")

    def test_loopback_rpc_is_never_labeled_live(self) -> None:
        self.assertEqual(watchdog.LiveRpc("http://127.0.0.1:8899").source, "local-rpc")
        self.assertEqual(watchdog.LiveRpc("https://api.mainnet-beta.solana.com").source, "live")

    def test_fixture_credit_is_labeled_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            config = watchdog.load_config(FIXTURE_CONFIG, state_path)
            first = watchdog.scan(config, watchdog.FixtureRpc(FIXTURE_RPC))
            self.assertEqual(len(first["alerts"]), 1)
            self.assertEqual(first["alerts"][0]["amount"], "2.5")
            self.assertEqual(first["alerts"][0]["asset"], "USDG")
            self.assertEqual(first["alerts"][0]["source"], "fixture")
            self.assertNotIn("explorer_url", first["alerts"][0])

            calls = json.loads(FIXTURE_RPC.read_text())["calls"][:2]
            replay_path = Path(directory) / "replay.json"
            replay_path.write_text(json.dumps({"calls": calls}))
            second = watchdog.scan(config, watchdog.FixtureRpc(replay_path))
            self.assertEqual(second["alerts"], [])
            self.assertEqual(second["scanned_signatures"], 0)

    def test_bootstrap_marks_history_without_alerting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = watchdog.load_config(FIXTURE_CONFIG, Path(directory) / "state.json")
            config = replace(config, bootstrap=True)
            result = watchdog.scan(config, watchdog.FixtureRpc(FIXTURE_RPC))
            self.assertEqual(result["alerts"], [])
            self.assertEqual(result["bootstrapped_accounts"], 1)

    def test_outgoing_balance_change_is_not_a_payout(self) -> None:
        token = watchdog.TokenConfig(
            "USDG", "2u1tszSeqZ3qBWF3uNGPFc8TzMk2tdiwknnRMWGWjGWH", 6, 1
        )
        transaction = json.loads(FIXTURE_RPC.read_text())["calls"][2]["result"]
        transaction["meta"]["postTokenBalances"][0]["uiTokenAmount"]["amount"] = "9000000"
        self.assertEqual(
            watchdog.detect_credit(
                transaction, "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA", token
            ),
            0,
        )


if __name__ == "__main__":
    unittest.main()
