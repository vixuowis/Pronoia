from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import config, db
from app.main import app


class SimulationRoutesTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        if db._conn is not None:
            db._conn.close()
            db._conn = None
        config.DB_PATH = str(Path(self.temporary.name) / "fever.db")
        db.init_db()
        self.case = db.create_case("simulation route test")
        self.graph = db.add_artifact(
            self.case["id"],
            None,
            "graph",
            "evidence graph",
            {
                "question": "监管调查后各参与方会如何行动？",
                "nodes": [
                    {
                        "id": "E1",
                        "kind": "evidence",
                        "title": "监管调查",
                        "source_kind": "official",
                        "source_ref": "https://example.com/notice",
                    }
                ],
                "edges": [],
            },
        )
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        if db._conn is not None:
            db._conn.close()
            db._conn = None
        self.temporary.cleanup()

    @staticmethod
    def completed_gateway(method, path, **kwargs):
        if method == "POST":
            return {
                "job_id": "simjob_fixed",
                "status": "queued",
                "stage": "queued",
                "progress": 0,
            }
        return {
            "job_id": "simjob_fixed",
            "status": "completed",
            "stage": "completed",
            "progress": 1,
            "finished_at": "2026-08-06T09:00:00+08:00",
            "error": None,
            "result": {
                "schema_version": "0.1.0",
                "execution": {"configured_actor_count": 4},
                "scenarios": [{"id": "branch-1", "label": "test branch"}],
                "warnings": ["test fixture"],
            },
        }

    def test_completed_job_writes_one_idempotent_simulation_artifact(self):
        body = {
            "source_graph_artifact_id": self.graph["id"],
            "mode": "quick",
        }
        with patch(
            "app.routes.simulations._gateway",
            side_effect=self.completed_gateway,
        ):
            first = self.client.post(
                f"/api/cases/{self.case['id']}/simulations", json=body
            )
            second = self.client.post(
                f"/api/cases/{self.case['id']}/simulations", json=body
            )
        self.assertEqual(first.status_code, 202)
        self.assertEqual(first.json()["id"], second.json()["id"])
        artifacts = db.list_artifacts(self.case["id"])
        simulations = [item for item in artifacts if item["kind"] == "simulation"]
        self.assertEqual(len(simulations), 1)
        self.assertEqual(simulations[0]["payload"]["scenarios"][0]["id"], "branch-1")

    def test_cancel_updates_persisted_job(self):
        remote_status = {"value": "running"}

        def gateway(method, path, **kwargs):
            if path.endswith("/cancel"):
                remote_status["value"] = "cancelling"
                return {
                    "job_id": "simjob_cancel",
                    "status": "cancelling",
                    "stage": "cancel_requested",
                    "progress": 0.5,
                }
            if method == "POST":
                return {
                    "job_id": "simjob_cancel",
                    "status": "queued",
                    "stage": "queued",
                    "progress": 0,
                }
            return {
                "job_id": "simjob_cancel",
                "status": remote_status["value"],
                "stage": "simulating",
                "progress": 0.5,
                "result": None,
            }

        with patch("app.routes.simulations._gateway", side_effect=gateway):
            started = self.client.post(
                f"/api/cases/{self.case['id']}/simulations",
                json={"source_graph_artifact_id": self.graph["id"]},
            )
            cancelled = self.client.post(
                f"/api/simulations/{started.json()['id']}/cancel", json={}
            )
        self.assertEqual(cancelled.status_code, 200)
        self.assertEqual(cancelled.json()["status"], "cancelling")
        self.assertEqual(cancelled.json()["stage"], "cancel_requested")


if __name__ == "__main__":
    unittest.main()
