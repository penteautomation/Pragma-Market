from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from pragma_market.cli import cli


class FakeClient:
    def __init__(self, *args, **kwargs):
        self.owner = kwargs.get("owner") or "demo-agent"
        self.wallet_path = Path(tempfile.gettempdir()) / "pragma-wallet.json"

    def get_network(self):
        return {
            "network": "devnet",
            "programId": "DemoProgram1111111111111111111111111111111111",
            "api_version": "1.0.0",
            "sdk_min_version": "0.1.0",
        }

    def get_open_markets(self, category=None, limit=None):
        markets = [
            {
                "marketId": "demo-market",
                "question": "Will Demo ship by Apr 20?",
                "category": "AI",
                "status": "open",
                "yesPriceCents": 54,
                "noPriceCents": 46,
                "fillCount": 2,
                "activeOwners": 3,
                "volumeMatchedCents": 1200,
                "closeTs": 1776717600,
                "resolutionSource": "https://example.com",
                "orderBook": {
                    "yesBids": [{"priceCents": 54, "quantity": 2}],
                    "noBids": [],
                    "yesAsks": [],
                    "noAsks": [],
                    "lastTradedPriceCents": 54,
                },
            }
        ]
        return {"count": len(markets[:limit]), "markets": markets[:limit]}

    def get_positions(self, owner=None, market_id=None):
        return {
            "positions": [
                {
                    "marketId": market_id or "demo-market",
                    "yes": {"quantity": 2},
                    "no": {"quantity": 0},
                    "claimablePayoutCents": 0,
                }
            ]
        }

    def get_portfolio(self, owner=None):
        return {"portfolio": {"freeCollateralCents": 1000, "lockedCollateralCents": 200}}

    def get_agent_profile(self, agent_name_or_id=None):
        return {
            "agent": {"id": "demo-agent", "name": agent_name_or_id or "demo-agent", "origin": "external"},
            "fills": [
                {
                    "fillId": "fill-1",
                    "marketId": "demo-market",
                    "maker": "demo-agent",
                    "taker": "other-agent",
                    "side": "buy_yes",
                    "priceCents": 54,
                    "quantity": 1,
                    "matchedAt": "2026-04-04T20:00:00Z",
                    "transactionSignatures": ["sig-1"],
                }
            ],
        }

    def get_leaderboard(self, limit=None):
        rows = [{"agentId": "demo-agent", "agentName": "demo-agent", "volumeMatchedCents": 1200}]
        return {"leaderboard": rows[:limit], "count": len(rows[:limit])}

    def get_recent_fills(self, limit=None, market_id=None):
        fills = [
            {
                "fillId": "fill-1",
                "marketId": market_id or "demo-market",
                "maker": "demo-agent",
                "taker": "other-agent",
                "side": "buy_yes",
                "priceCents": 54,
                "quantity": 1,
                "matchedAt": "2026-04-04T20:00:00Z",
                "transactionSignatures": ["sig-1"],
            }
        ]
        return {"recentBets": fills[:limit], "count": len(fills[:limit])}

    def get_markets(self, category=None, status="open"):
        return self.get_open_markets(category=category, limit=1)


class CliTests(unittest.TestCase):
    def setUp(self):
        self.runner = CliRunner()

    @patch("pragma_market.cli._client", return_value=FakeClient())
    def test_open_markets_outputs_agent_friendly_json(self, _client_factory):
        result = self.runner.invoke(cli, ["open-markets", "--limit", "1"])
        self.assertEqual(result.exit_code, 0, result.output)
        payload = json.loads(result.output)
        self.assertEqual(payload["command"], "open-markets")
        self.assertEqual(payload["network"]["mode"], "devnet")
        self.assertEqual(payload["markets"][0]["marketId"], "demo-market")

    @patch("pragma_market.cli._client", return_value=FakeClient())
    def test_my_positions_outputs_owner_snapshot(self, _client_factory):
        result = self.runner.invoke(cli, ["my-positions"])
        self.assertEqual(result.exit_code, 0, result.output)
        payload = json.loads(result.output)
        self.assertEqual(payload["command"], "my-positions")
        self.assertEqual(payload["owner"], "demo-agent")
        self.assertIn("portfolio", payload)

    @patch("pragma_market.cli._client", return_value=FakeClient())
    def test_leaderboard_outputs_json(self, _client_factory):
        result = self.runner.invoke(cli, ["leaderboard"])
        self.assertEqual(result.exit_code, 0, result.output)
        payload = json.loads(result.output)
        self.assertEqual(payload["command"], "leaderboard")
        self.assertEqual(payload["count"], 1)

    @patch("pragma_market.cli._client", return_value=FakeClient())
    def test_markets_json_outputs_envelope(self, _client_factory):
        result = self.runner.invoke(cli, ["markets", "--json"])
        self.assertEqual(result.exit_code, 0, result.output)
        payload = json.loads(result.output)
        self.assertEqual(payload["command"], "markets")
        self.assertEqual(payload["markets"][0]["yesPriceCents"], 54)
        self.assertEqual(payload["markets"][0]["agentTradeHint"]["side"], "no")

    @patch("pragma_market.cli._client", return_value=FakeClient())
    def test_fills_outputs_agent_perspective(self, _client_factory):
        result = self.runner.invoke(cli, ["fills"])
        self.assertEqual(result.exit_code, 0, result.output)
        payload = json.loads(result.output)
        self.assertEqual(payload["command"], "fills")
        self.assertEqual(payload["recentFills"][0]["perspective"], "maker")

    def test_quickstart_scaffolds_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "starter"
            result = self.runner.invoke(cli, ["quickstart", "--dir", str(target)])
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertTrue((target / "agent.py").exists())
            self.assertTrue((target / "README.md").exists())
            self.assertTrue((target / ".env.example").exists())

    def test_example_agent_exports_template(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "agent.py"
            result = self.runner.invoke(
                cli,
                ["example-agent", "--template", "polymarket-style", "--output", str(target)],
            )
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("PragmaClient", target.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
