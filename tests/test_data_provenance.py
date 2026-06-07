import os
import io
import sqlite3
import shutil
import unittest
import uuid
from contextlib import redirect_stdout

import champion_predictor
import external_intelligence
import odds_crawler


WORKSPACE_TMP = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".test-tmp")


def temp_workspace_dir():
    os.makedirs(WORKSPACE_TMP, exist_ok=True)
    path = os.path.join(WORKSPACE_TMP, f"case-{uuid.uuid4().hex}")
    os.makedirs(path, exist_ok=False)

    class TempDir:
        def __enter__(self):
            return path

        def __exit__(self, exc_type, exc, tb):
            shutil.rmtree(path, ignore_errors=True)

    return TempDir()


def create_champion_db(path, teams):
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE teams (
            id INTEGER PRIMARY KEY,
            name TEXT UNIQUE,
            confederation TEXT,
            elo_rating REAL,
            fifa_rank INTEGER,
            pi_rating_home REAL,
            pi_rating_away REAL,
            berrar_att REAL,
            berrar_def REAL,
            fbref_xg_diff REAL,
            injury_count INTEGER,
            sentiment_score REAL,
            opta_win_prob REAL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE matches (
            match_num INTEGER PRIMARY KEY,
            group_or_stage TEXT,
            home_team TEXT,
            away_team TEXT,
            city TEXT,
            status TEXT,
            home_goals INTEGER,
            away_goals INTEGER
        )
        """
    )
    for idx, team in enumerate(teams, 1):
        conn.execute(
            """
            INSERT INTO teams (
                id, name, confederation, elo_rating, fifa_rank,
                pi_rating_home, pi_rating_away, berrar_att, berrar_def,
                fbref_xg_diff, injury_count, sentiment_score, opta_win_prob
            )
            VALUES (?, ?, 'TEST', 1500, 50, 0, 0, 1, 1, 0, 0, 0, 0)
            """,
            (idx, team),
        )
    conn.commit()
    conn.close()


class DataProvenanceTests(unittest.TestCase):
    def test_champion_prediction_stores_only_registered_teams(self):
        with temp_workspace_dir() as tmp:
            db_path = os.path.join(tmp, "fifa_2026.db")
            create_champion_db(db_path, ["Spain", "Bosnia-Herzegovina"])

            old_db_path = champion_predictor.DB_PATH
            old_market = champion_predictor.get_market_probs
            old_simulate = champion_predictor.simulate_tournament
            try:
                champion_predictor.DB_PATH = db_path
                champion_predictor.get_market_probs = lambda api_key: {
                    "Spain": 0.50,
                    "Bosnia & Herzegovina": 0.25,
                    "Italy": 0.25,
                }
                champion_predictor.simulate_tournament = lambda matches, cache, n_sims: (
                    {"Spain": 0.60, "Bosnia-Herzegovina": 0.40},
                    {},
                )

                champion_predictor.run_champion_prediction(
                    api_key="", n_sims=0, alpha=1.0, store=True
                )

                conn = sqlite3.connect(db_path)
                rows = conn.execute(
                    """
                    SELECT team, market_prob
                    FROM champion_predictions
                    ORDER BY team
                    """
                ).fetchall()
                conn.close()
            finally:
                champion_predictor.DB_PATH = old_db_path
                champion_predictor.get_market_probs = old_market
                champion_predictor.simulate_tournament = old_simulate

            self.assertEqual(
                [team for team, _ in rows],
                ["Bosnia-Herzegovina", "Spain"],
            )
            market_by_team = dict(rows)
            self.assertGreater(market_by_team["Bosnia-Herzegovina"], 0)

    def test_odds_migration_adds_feed_source_columns(self):
        with temp_workspace_dir() as tmp:
            db_path = os.path.join(tmp, "fifa_2026.db")
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE matches (match_num INTEGER PRIMARY KEY)")
            conn.commit()
            conn.close()

            old_db_path = odds_crawler.DB_PATH
            old_log_path = odds_crawler.LOG_PATH
            try:
                odds_crawler.DB_PATH = db_path
                odds_crawler.LOG_PATH = os.path.join(tmp, "sync.log")
                odds_crawler.migrate_odds_columns()
                conn = sqlite3.connect(db_path)
                cols = {row[1] for row in conn.execute("PRAGMA table_info(matches)")}
                conn.close()
            finally:
                odds_crawler.DB_PATH = old_db_path
                odds_crawler.LOG_PATH = old_log_path

            self.assertIn("odds_source", cols)
            self.assertIn("odds_last_update", cols)
            self.assertIn("odds_bookmaker_keys", cols)

    def test_external_intelligence_uses_model_prior_names(self):
        self.assertTrue(hasattr(external_intelligence, "MODEL_PRIOR_XG_DIFF"))
        self.assertTrue(hasattr(external_intelligence, "get_model_prior_xg_diff"))
        self.assertFalse(hasattr(external_intelligence, "FBREF_BASE_DATA"))
        self.assertIn(
            "model prior",
            (external_intelligence.run_external_intelligence_sync.__doc__ or "").lower(),
        )

    def test_champion_market_api_error_does_not_log_api_key(self):
        secret = "SECRET_API_KEY"
        old_get = champion_predictor.requests.get
        try:
            def raise_with_secret(*args, **kwargs):
                raise RuntimeError(f"request failed: https://example.test/?apiKey={secret}")

            champion_predictor.requests.get = raise_with_secret
            output = io.StringIO()
            with redirect_stdout(output):
                result = champion_predictor.fetch_market_api(secret)
        finally:
            champion_predictor.requests.get = old_get

        self.assertIsNone(result)
        self.assertNotIn(secret, output.getvalue())


if __name__ == "__main__":
    unittest.main()
