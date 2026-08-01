#!/usr/bin/env python3
"""Run a signed ZeroClaw webhook turn against a live Solana RPC.

This demo uses a deterministic local model adapter so reviewers can reproduce
the channel/tool loop without an API key. The payout skill still contacts the
HTTPS RPC configured by the operator; fixture and loopback RPCs are rejected.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen


TOOL_NAME = "solana-payout-watchdog__check_payouts"


def redact_wallet(value: str) -> str:
    return f"{value[:4]}…{value[-4:]}" if len(value) > 12 else "[redacted]"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_port(port: int, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.1)
    raise TimeoutError(f"ZeroClaw webhook did not start on port {port}")


def json_from_tool_result(messages: list[dict[str, object]]) -> dict[str, object] | None:
    for message in reversed(messages):
        if message.get("role") == "system":
            continue
        content = str(message.get("content", ""))
        if "<tool_result" not in content:
            continue
        match = re.search(r"\{.*\}", content, flags=re.DOTALL)
        if not match:
            continue
        try:
            value = json.loads(match.group(0))
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def completion(content: str) -> dict[str, object]:
    return {
        "choices": [
            {
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ]
    }


class DemoHandler(BaseHTTPRequestHandler):
    server: "DemoServer"

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def send_json(self, value: object) -> None:
        body = json.dumps(value).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_sse(self, content: str) -> None:
        event = {
            "choices": [
                {"index": 0, "delta": {"content": content}, "finish_reason": "stop"}
            ]
        }
        body = f"data: {json.dumps(event)}\n\ndata: [DONE]\n\n".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def respond(self, request: dict[str, object], content: str) -> None:
        if request.get("stream"):
            self.send_sse(content)
        else:
            self.send_json(completion(content))

    def do_GET(self) -> None:
        self.send_json({"object": "list", "data": [{"id": "deterministic-demo"}]})

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length) or b"{}")
        if self.path == "/callback":
            self.server.callback = request
            print(f"[callback] {request.get('content', '')}", flush=True)
            self.server.callback_event.set()
            self.send_json({"ok": True})
            return

        if not self.path.endswith("/chat/completions"):
            self.send_error(404)
            return

        messages = request.get("messages", [])
        if not isinstance(messages, list):
            messages = []
        latest_user = next(
            (
                str(message.get("content", ""))
                for message in reversed(messages)
                if isinstance(message, dict) and message.get("role") == "user"
            ),
            "",
        )
        system_text = "\n".join(
            str(message.get("content", ""))
            for message in messages
            if isinstance(message, dict) and message.get("role") == "system"
        )

        if "Decide whether the assistant should send any visible reply" in latest_user:
            self.respond(request, "REPLY")
            return
        if "You are a memory consolidation engine" in system_text:
            self.respond(
                request,
                json.dumps(
                    {
                        "history_entry": "Checked for finalized USDG and USDC credits.",
                        "memory_update": None,
                    }
                ),
            )
            return

        result = json_from_tool_result(
            [message for message in messages if isinstance(message, dict)]
        )
        if result is None:
            print(f"[agent] calling allowlisted tool: {TOOL_NAME}", flush=True)
            self.respond(
                request,
                f'<tool_call>\n{{"name":"{TOOL_NAME}","arguments":{{}}}}\n</tool_call>',
            )
            return

        mode = str(result.get("mode", "unknown"))
        commitment = str(result.get("commitment", "unknown"))
        wallet = redact_wallet(str(result.get("wallet", "")))
        alerts = result.get("alerts", [])
        alert_count = len(alerts) if isinstance(alerts, list) else 0
        print(
            "[skill] "
            f"mode={mode} commitment={commitment} alerts={alert_count} "
            f"wallet={wallet}",
            flush=True,
        )
        if mode == "live" and commitment == "finalized":
            if alert_count:
                final_text = (
                    "Live finalized Solana scan complete. "
                    f"Found {alert_count} new USDG/USDC payout credit(s)."
                )
            else:
                final_text = (
                    "Live finalized Solana scan complete. No new USDG or USDC "
                    "payout credits were found for the configured public wallet."
                )
        else:
            final_text = (
                f"Demo scan complete in {mode} mode. This is not real payout evidence."
            )
        self.respond(request, final_text)


class DemoServer(ThreadingHTTPServer):
    callback_event: threading.Event
    callback: dict[str, object] | None


def write_runtime_config(
    config_dir: Path, model_port: int, webhook_port: int, secret: str
) -> None:
    content = f'''schema_version = 3

[providers.models.custom.demo]
uri = "http://127.0.0.1:{model_port}/v1"
model = "deterministic-demo"
wire_api = "chat_completions"

[skill_bundles.solana]

[agents.payout_watchdog]
enabled = true
channels = ["webhook.payout"]
model_provider = "custom.demo"
risk_profile = "payout_readonly"
runtime_profile = "payout_demo"
skill_bundles = ["solana"]

[risk_profiles.payout_readonly]
level = "supervised"
workspace_only = true
allowed_commands = ["solana-payout-watchdog"]
allowed_tools = ["{TOOL_NAME}"]
auto_approve = ["{TOOL_NAME}"]
block_high_risk_commands = true
require_approval_for_medium_risk = true

[runtime_profiles.payout_demo]
agentic = true
max_tool_iterations = 4
max_actions_per_hour = 20
max_cost_per_day_cents = 1
agentic_timeout_secs = 60

[channels.webhook.payout]
enabled = true
port = {webhook_port}
listen_path = "/payout"
send_url = "http://127.0.0.1:{model_port}/callback"
secret = "{secret}"
excluded_tools = ["shell", "file_write", "http_request", "browser", "cron_add"]
'''
    (config_dir / "config.toml").write_text(content)
    os.chmod(config_dir / "config.toml", 0o600)


def run(args: argparse.Namespace) -> int:
    zeroclaw = Path(args.zeroclaw).expanduser().resolve()
    repo = Path(args.repo).expanduser().resolve()
    watchdog_config = Path(args.config).expanduser().resolve()
    if not zeroclaw.is_file():
        raise FileNotFoundError(f"ZeroClaw binary not found: {zeroclaw}")
    if not (repo / "pyproject.toml").is_file():
        raise FileNotFoundError(f"watchdog repository not found: {repo}")
    if not watchdog_config.is_file():
        raise FileNotFoundError(f"watchdog config not found: {watchdog_config}")

    for remaining in range(args.countdown, 0, -1):
        print(f"Starting signed live demo in {remaining}…", flush=True)
        time.sleep(1)

    model_port = free_port()
    webhook_port = free_port()
    secret = secrets.token_hex(32)
    server = DemoServer(("127.0.0.1", model_port), DemoHandler)
    server.callback_event = threading.Event()
    server.callback = None
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    daemon: subprocess.Popen[str] | None = None
    with tempfile.TemporaryDirectory(prefix="zeroclaw-payout-demo-") as raw_dir:
        config_dir = Path(raw_dir)
        clean_source = config_dir / "skill-source"
        shutil.copytree(
            repo,
            clean_source,
            ignore=shutil.ignore_patterns(
                ".git",
                ".demo",
                "__pycache__",
                "*.pyc",
                "build",
                "*.egg-info",
                "watchdog.toml",
                "payout-watchdog.toml",
                "watchdog-state.json",
            ),
        )
        venv = config_dir / "venv"
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
        cli = venv / "bin" / "solana-payout-watchdog"
        pip = venv / "bin" / "pip"
        subprocess.run(
            [
                str(pip),
                "install",
                "--quiet",
                "--disable-pip-version-check",
                str(clean_source),
            ],
            check=True,
        )
        subprocess.run(
            [str(zeroclaw), "skills", "bundle", "add", "solana", "--config-dir", str(config_dir)],
            check=True,
            stdout=subprocess.DEVNULL,
        )
        subprocess.run(
            [
                str(zeroclaw),
                "skills",
                "install",
                str(clean_source),
                "--bundle",
                "solana",
                "--config-dir",
                str(config_dir),
                "--no-tier-banner",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
        )
        write_runtime_config(config_dir, model_port, webhook_port, secret)

        workspace = config_dir / "agents" / "payout_watchdog" / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(watchdog_config, workspace / "payout-watchdog.toml")
        os.chmod(workspace / "payout-watchdog.toml", 0o600)

        version = subprocess.run(
            [str(zeroclaw), "--version"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        print(f"[runtime] {version}; signed webhook channel readying", flush=True)
        environment = os.environ.copy()
        environment["PATH"] = f"{cli.parent}{os.pathsep}{environment.get('PATH', '')}"
        daemon = subprocess.Popen(
            [
                str(zeroclaw),
                "daemon",
                "--config-dir",
                str(config_dir),
                "--host",
                "127.0.0.1",
                "--port",
                "0",
                "--log-level",
                "error",
            ],
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            wait_for_port(webhook_port)
            payload = {
                "sender": "bounty-demo",
                "content": (
                    "Run the Solana payout watchdog now and report whether the "
                    "configured public wallet has new finalized USDG or USDC credits."
                ),
                "thread_id": "signed-live-demo",
            }
            body = json.dumps(payload, separators=(",", ":")).encode()
            signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
            print("[channel] sending HMAC-SHA256 authenticated webhook", flush=True)
            request = Request(
                f"http://127.0.0.1:{webhook_port}/payout",
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Webhook-Signature": f"sha256={signature}",
                },
                method="POST",
            )
            with urlopen(request, timeout=30) as response:
                print(f"[channel] ZeroClaw accepted request: HTTP {response.status}", flush=True)
            if not server.callback_event.wait(timeout=90):
                raise TimeoutError("ZeroClaw did not deliver its callback")
            print("[result] PASS — real channel loop and live finalized chain read", flush=True)
            return 0
        finally:
            if daemon.poll() is None:
                daemon.send_signal(signal.SIGINT)
                try:
                    daemon.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    daemon.terminate()
                    daemon.wait(timeout=5)
            if daemon.returncode not in (0, -signal.SIGINT):
                output = daemon.stdout.read() if daemon.stdout else ""
                if output.strip():
                    print(output[-4000:], file=sys.stderr)
            server.shutdown()
            server.server_close()


def parse_args() -> argparse.Namespace:
    repo_default = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zeroclaw", default=shutil.which("zeroclaw"))
    parser.add_argument("--repo", default=str(repo_default))
    parser.add_argument("--config", default=str(repo_default / "payout-watchdog.toml"))
    parser.add_argument("--countdown", type=int, default=0)
    args = parser.parse_args()
    if not args.zeroclaw:
        parser.error("--zeroclaw is required when zeroclaw is not on PATH")
    if args.countdown < 0:
        parser.error("--countdown must be non-negative")
    return args


if __name__ == "__main__":
    try:
        raise SystemExit(run(parse_args()))
    except (FileNotFoundError, TimeoutError, subprocess.CalledProcessError) as error:
        print(f"demo failed: {error}", file=sys.stderr)
        raise SystemExit(1)
