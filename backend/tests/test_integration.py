"""Integration tests for the LangGraph workflow, human gate revision loop, and FastAPI endpoints."""
from __future__ import annotations

import asyncio
import os
import tempfile
import unittest

import httpx

from backend.app.config import Settings
from backend.app.main import create_app


class TestGraphAndAPIIntegration(unittest.TestCase):
    def test_full_lifecycle_including_revision_and_sse_resume(self) -> None:
        async def _run() -> None:
            with tempfile.TemporaryDirectory() as tmp:
                settings = Settings(
                    database_path=os.path.join(tmp, "int_runs.db"),
                    checkpoint_db_path=os.path.join(tmp, "int_ckpt.db"),
                    stub_external_apis=True,
                    rate_limit_rpm=6000,
                    max_request_bytes=4096,
                )
                app = create_app(settings)
                async with httpx.AsyncClient(app=app, base_url="http://testserver") as client:
                    # 1. Health check
                    h = await client.get("/health")
                    self.assertEqual(h.status_code, 200)
                    self.assertEqual(h.json()["status"], "ok")

                    # 2. Request size limit guard (413)
                    oversized = "x" * 5000
                    too_big = await client.post(
                        "/runs",
                        json={"question": oversized, "token_budget": 16000, "max_loops": 2, "support_threshold": 0.75},
                    )
                    self.assertEqual(too_big.status_code, 413)
                    self.assertEqual(too_big.json()["error_code"], "PAYLOAD_TOO_LARGE")

                    # 3. Create run and wait for human_gate interrupt
                    created = await client.post(
                        "/runs?wait_for_interrupt=true",
                        json={
                            "question": "How do speculative decoding algorithms accelerate autoregressive LLM inference?",
                            "token_budget": 32000,
                            "max_loops": 3,
                            "support_threshold": 0.75,
                        },
                    )
                    self.assertEqual(created.status_code, 201)
                    run_id = created.json()["run_id"]
                    self.assertEqual(created.json()["status"], "awaiting_approval")

                    # 4. Request a revision at human_gate -> loops back to retriever -> synthesizer -> verifier -> human_gate
                    revised = await client.post(
                        f"/runs/{run_id}/decision",
                        json={
                            "action": "revise",
                            "feedback": "Include tail latency p99 comparisons across 70B models.",
                        },
                    )
                    self.assertEqual(revised.status_code, 200)
                    self.assertEqual(revised.json()["status"], "awaiting_approval")
                    self.assertEqual(
                        revised.json()["human_feedback"],
                        "Include tail latency p99 comparisons across 70B models.",
                    )

                    # 5. Approve at human_gate -> finalizer completes report
                    approved = await client.post(
                        f"/runs/{run_id}/decision",
                        json={"action": "approve"},
                    )
                    self.assertEqual(approved.status_code, 200)
                    self.assertEqual(approved.json()["status"], "completed")

                    # 6. Fetch Markdown report
                    report = await client.get(f"/runs/{run_id}/report.md")
                    self.assertEqual(report.status_code, 200)
                    self.assertIn("# NEXUS//AGENTIS Verified Research Report", report.text)
                    self.assertIn("Per-Claim Entailment Verification Table", report.text)

                    # 7. Verify tamper-evident ledger chain
                    ledger = await client.get(f"/runs/{run_id}/ledger/verify")
                    self.assertEqual(ledger.status_code, 200)
                    self.assertTrue(ledger.json()["valid"])
                    self.assertGreater(ledger.json()["total_entries"], 30)

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
