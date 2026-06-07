import os
import sqlite3
import unittest

import build_static
import external_predictions


class ExternalPredictionSourceTests(unittest.TestCase):
    def test_source_catalog_marks_only_direct_free_sources_auto(self):
        with sqlite3.connect(":memory:") as conn:
            external_predictions.ensure_default_data(conn)

            rows = conn.execute(
                """
                SELECT source_key, free_direct, sync_mode
                FROM prediction_sources
                ORDER BY source_key
                """
            ).fetchall()

        self.assertEqual(len(rows), 8)
        by_key = {key: (free_direct, sync_mode) for key, free_direct, sync_mode in rows}
        self.assertEqual(by_key["leadafrik"], (1, "auto"))
        self.assertEqual(by_key["zeileis_groll"], (1, "auto"))
        self.assertEqual(by_key["goldman_sachs"], (1, "partial_pdf"))
        self.assertEqual(by_key["opta_analyst"], (0, "manual_snapshot"))
        self.assertEqual(by_key["calibrsports"], (0, "manual_review"))
        self.assertEqual(by_key["squawka"], (0, "manual_review"))
        self.assertEqual(by_key["statz"], (0, "manual_review"))
        self.assertEqual(by_key["themodelsays"], (0, "manual_review"))

    def test_external_champion_consensus_uses_seeded_free_snapshots(self):
        with sqlite3.connect(":memory:") as conn:
            external_predictions.ensure_default_data(conn)

            consensus = external_predictions.load_champion_consensus(conn, limit=5)

        teams = [row["team"] for row in consensus]
        self.assertIn("Spain", teams)
        spain = next(row for row in consensus if row["team"] == "Spain")
        self.assertGreaterEqual(spain["source_count"], 4)
        self.assertGreater(spain["avg_prob"], 0.15)

    def test_default_seed_does_not_downgrade_live_snapshot(self):
        with sqlite3.connect(":memory:") as conn:
            external_predictions.ensure_default_data(conn)
            external_predictions.upsert_champion_snapshot(
                conn,
                "zeileis_groll",
                "2026-06-03",
                {"Spain": 0.146},
                "live_html",
            )
            conn.commit()

            external_predictions.ensure_default_data(conn)

            status = conn.execute(
                """
                SELECT last_sync_status
                FROM prediction_sources
                WHERE source_key = 'zeileis_groll'
                """
            ).fetchone()[0]
            value = conn.execute(
                """
                SELECT champion_prob
                FROM external_champion_predictions
                WHERE source_key = 'zeileis_groll'
                  AND snapshot_date = '2026-06-03'
                  AND team = 'Spain'
                """
            ).fetchone()[0]

        self.assertEqual(status, "live_html")
        self.assertEqual(value, 0.146)

    def test_leadafrik_parser_handles_line_separated_outlook_cards(self):
        html = """
        <section>
          <div>#1</div><div>Spain</div><div>23.3%</div><div>to win</div>
          <div>SF 41%</div><div>QF 52%</div>
          <div>#2</div><div>Argentina</div><div>15.3%</div><div>to win</div>
        </section>
        """

        probs = external_predictions.parse_leadafrik_champion_probs(html)

        self.assertEqual(probs["Spain"], 0.233)
        self.assertEqual(probs["Argentina"], 0.153)

    def test_build_static_exports_external_payload_and_source_board(self):
        sources = [
            {
                "source_key": "leadafrik",
                "source_name": "LeadAfrik Probability Lab",
                "sync_mode": "auto",
                "free_direct": 1,
                "coverage": "104 matches + champion outlook",
                "trust_tier": "transparent",
                "snapshot_date": "2026-05-14",
                "last_sync_status": "seeded_snapshot",
                "notes": "HTML-readable probabilities.",
                "source_url": "https://example.test/leadafrik",
            }
        ]
        consensus = [
            {
                "team": "Spain",
                "avg_prob": 0.184,
                "source_count": 4,
                "sources": "LeadAfrik, Zeileis/Groll, Goldman Sachs, Opta Analyst",
            }
        ]

        html = build_static.build_source_board(sources, consensus)
        payload = build_static.external_payload(sources, consensus)

        self.assertIn("External Source Board", html)
        self.assertIn("LeadAfrik Probability Lab", html)
        self.assertIn("AUTO", html)
        self.assertIn("Spain", html)
        self.assertEqual(payload["external_sources"][0]["source_key"], "leadafrik")
        self.assertEqual(payload["external_champion_consensus"][0]["team"], "Spain")


if __name__ == "__main__":
    unittest.main()
