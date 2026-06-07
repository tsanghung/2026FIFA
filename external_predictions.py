"""
External 2026 World Cup prediction source registry and snapshots.

This module keeps external model data separate from the project's own model and
market-odds fields. Each value is stored with source, snapshot date, access mode,
and quality labels so the UI can show what is automated, partial, or manual.
"""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
from datetime import datetime
from typing import Iterable

import requests
from bs4 import BeautifulSoup

from sync_fifa import normalize_team_name


HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "fifa_2026.db")


SOURCE_CATALOG = [
    {
        "source_key": "leadafrik",
        "source_name": "LeadAfrik Probability Lab",
        "source_url": "https://www.leadafrik.com/models/probability-lab/world-cup-2026",
        "source_type": "transparent_statistical_model",
        "access_tier": "free_public_html",
        "sync_mode": "auto",
        "free_direct": 1,
        "coverage": "104 matches + champion outlook",
        "trust_tier": "transparent",
        "snapshot_date": "2026-05-14",
        "notes": "HTML page exposes match probabilities and tournament outlook.",
    },
    {
        "source_key": "zeileis_groll",
        "source_name": "Zeileis/Groll Academic Forecast",
        "source_url": "https://www.zeileis.org/news/fifa2026/",
        "source_type": "academic_machine_learning",
        "access_tier": "free_public_html",
        "sync_mode": "auto",
        "free_direct": 1,
        "coverage": "champion, survival, possible-match probabilities",
        "trust_tier": "academic",
        "snapshot_date": "2026-06-03",
        "notes": "Public article plus interactive HTML charts.",
    },
    {
        "source_key": "goldman_sachs",
        "source_name": "Goldman Sachs Statistical Model",
        "source_url": "https://static.poder360.com.br/2026/05/The-World-Cup-and-Economics_-World-Cup-2026_-Predictions-Probabilities-and-Paths-to-Victory.pdf",
        "source_type": "institutional_statistical_model",
        "access_tier": "free_public_pdf",
        "sync_mode": "partial_pdf",
        "free_direct": 1,
        "coverage": "stage probabilities from PDF table",
        "trust_tier": "institutional",
        "snapshot_date": "2026-05-29",
        "notes": "Free PDF; table extraction is partial and snapshot-based.",
    },
    {
        "source_key": "opta_analyst",
        "source_name": "Opta Analyst Supercomputer",
        "source_url": "https://theanalyst.com/articles/who-will-win-2026-fifa-world-cup-predictions-opta-supercomputer",
        "source_type": "authority_supercomputer",
        "access_tier": "free_article_partial",
        "sync_mode": "manual_snapshot",
        "free_direct": 0,
        "coverage": "article-level champion and stage notes",
        "trust_tier": "authority",
        "snapshot_date": "2026-06-01",
        "notes": "Free article, but not a stable full data feed.",
    },
    {
        "source_key": "squawka",
        "source_name": "Squawka AI Predictor",
        "source_url": "https://www.squawka.com/en/news/squawkas-world-cup-ai-predictor/",
        "source_type": "media_ai_predictor",
        "access_tier": "free_article_partial",
        "sync_mode": "manual_review",
        "free_direct": 0,
        "coverage": "article picks, not stable full dataset",
        "trust_tier": "media",
        "snapshot_date": None,
        "notes": "Use only after manual review; not a direct full feed.",
    },
    {
        "source_key": "statz",
        "source_name": "Statz",
        "source_url": "https://statz.ai/",
        "source_type": "commercial_prediction_site",
        "access_tier": "free_site_partial",
        "sync_mode": "manual_review",
        "free_direct": 0,
        "coverage": "fixtures and described model projections",
        "trust_tier": "commercial",
        "snapshot_date": None,
        "notes": "Visible pages are not a stable public prediction API.",
    },
    {
        "source_key": "calibrsports",
        "source_name": "CalibrSports",
        "source_url": "https://www.calibrsports.com/wc/what-calibrsports-offers",
        "source_type": "commercial_ml_betting_analytics",
        "access_tier": "freemium",
        "sync_mode": "manual_review",
        "free_direct": 0,
        "coverage": "free 1X2 tier described, deeper markets paid",
        "trust_tier": "commercial",
        "snapshot_date": None,
        "notes": "Freemium product; do not scrape as an unrestricted source.",
    },
    {
        "source_key": "themodelsays",
        "source_name": "TheModelSays",
        "source_url": "https://www.themodelsays.com/",
        "source_type": "open_beta_ai_predictor",
        "access_tier": "free_open_beta",
        "sync_mode": "manual_review",
        "free_direct": 0,
        "coverage": "sample picks and bracket UI",
        "trust_tier": "experimental",
        "snapshot_date": None,
        "notes": "Open beta page lacks a stable complete data export.",
    },
]


STATIC_CHAMPION_SNAPSHOTS = {
    "leadafrik": {
        "snapshot_date": "2026-05-14",
        "data_quality": "seeded_snapshot_top",
        "probs": {
            "Spain": 0.233,
            "Argentina": 0.153,
            "France": 0.123,
        },
    },
    "zeileis_groll": {
        "snapshot_date": "2026-06-03",
        "data_quality": "seeded_snapshot_article",
        "probs": {
            "Spain": 0.145,
            "England": 0.124,
            "France": 0.124,
            "Germany": 0.112,
        },
    },
    "goldman_sachs": {
        "snapshot_date": "2026-05-29",
        "data_quality": "seeded_snapshot_pdf",
        "probs": {
            "Spain": 0.257,
            "France": 0.189,
            "Argentina": 0.143,
            "Brazil": 0.076,
            "Netherlands": 0.052,
            "England": 0.050,
            "Portugal": 0.048,
            "Germany": 0.045,
            "Colombia": 0.022,
            "Croatia": 0.017,
            "Norway": 0.016,
            "Mexico": 0.008,
            "Senegal": 0.008,
            "Ecuador": 0.008,
            "Belgium": 0.007,
            "Switzerland": 0.007,
            "Turkiye": 0.006,
            "USA": 0.005,
            "Japan": 0.005,
            "Austria": 0.004,
            "Uruguay": 0.004,
            "Paraguay": 0.003,
            "Morocco": 0.003,
            "Canada": 0.003,
            "Uzbekistan": 0.002,
            "Australia": 0.002,
            "Czechia": 0.002,
            "Scotland": 0.001,
            "Algeria": 0.001,
            "Iran": 0.001,
            "Panama": 0.001,
            "South Korea": 0.001,
            "Egypt": 0.001,
            "Sweden": 0.001,
            "Jordan": 0.001,
        },
    },
    "opta_analyst": {
        "snapshot_date": "2026-06-01",
        "data_quality": "manual_article_snapshot",
        "probs": {
            "Spain": 0.161,
            "France": 0.130,
            "England": 0.112,
            "Argentina": 0.104,
            "Brazil": 0.083,
            "Portugal": 0.058,
            "Germany": 0.050,
            "Netherlands": 0.045,
            "Belgium": 0.030,
            "Uruguay": 0.028,
            "Croatia": 0.022,
            "Morocco": 0.019,
        },
    },
}


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS prediction_sources (
            source_key TEXT PRIMARY KEY,
            source_name TEXT NOT NULL,
            source_url TEXT NOT NULL,
            source_type TEXT NOT NULL,
            access_tier TEXT NOT NULL,
            sync_mode TEXT NOT NULL,
            free_direct INTEGER NOT NULL,
            coverage TEXT NOT NULL,
            trust_tier TEXT NOT NULL,
            snapshot_date TEXT,
            last_sync_at TEXT,
            last_sync_status TEXT,
            notes TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS external_champion_predictions (
            source_key TEXT NOT NULL,
            snapshot_date TEXT NOT NULL,
            team TEXT NOT NULL,
            champion_prob REAL NOT NULL,
            source_url TEXT NOT NULL,
            data_quality TEXT NOT NULL,
            ingested_at TEXT NOT NULL,
            PRIMARY KEY (source_key, snapshot_date, team),
            FOREIGN KEY (source_key) REFERENCES prediction_sources(source_key)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS external_match_predictions (
            source_key TEXT NOT NULL,
            snapshot_date TEXT NOT NULL,
            match_num INTEGER,
            home_team TEXT,
            away_team TEXT,
            home_prob REAL,
            draw_prob REAL,
            away_prob REAL,
            pred_score TEXT,
            source_url TEXT NOT NULL,
            data_quality TEXT NOT NULL,
            ingested_at TEXT NOT NULL,
            PRIMARY KEY (source_key, snapshot_date, match_num)
        )
        """
    )


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def seed_source_catalog(conn: sqlite3.Connection) -> None:
    now = _now()
    for source in SOURCE_CATALOG:
        status = "seeded_snapshot" if source["source_key"] in STATIC_CHAMPION_SNAPSHOTS else "not_synced"
        conn.execute(
            """
            INSERT INTO prediction_sources (
                source_key, source_name, source_url, source_type, access_tier,
                sync_mode, free_direct, coverage, trust_tier, snapshot_date,
                last_sync_at, last_sync_status, notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_key) DO UPDATE SET
                source_name=excluded.source_name,
                source_url=excluded.source_url,
                source_type=excluded.source_type,
                access_tier=excluded.access_tier,
                sync_mode=excluded.sync_mode,
                free_direct=excluded.free_direct,
                coverage=excluded.coverage,
                trust_tier=excluded.trust_tier,
                snapshot_date=COALESCE(prediction_sources.snapshot_date, excluded.snapshot_date),
                last_sync_at=COALESCE(prediction_sources.last_sync_at, excluded.last_sync_at),
                last_sync_status=COALESCE(prediction_sources.last_sync_status, excluded.last_sync_status),
                notes=excluded.notes
            """,
            (
                source["source_key"],
                source["source_name"],
                source["source_url"],
                source["source_type"],
                source["access_tier"],
                source["sync_mode"],
                source["free_direct"],
                source["coverage"],
                source["trust_tier"],
                source["snapshot_date"],
                now,
                status,
                source["notes"],
            ),
        )


def upsert_champion_snapshot(
    conn: sqlite3.Connection,
    source_key: str,
    snapshot_date: str,
    probs: dict[str, float],
    data_quality: str,
    replace: bool = True,
) -> int:
    source = next(item for item in SOURCE_CATALOG if item["source_key"] == source_key)
    ingested_at = _now()
    count = 0
    for raw_team, prob in probs.items():
        if prob is None:
            continue
        team = normalize_team_name(raw_team)
        values = (
            source_key,
            snapshot_date,
            team,
            float(prob),
            source["source_url"],
            data_quality,
            ingested_at,
        )
        if replace:
            conn.execute(
                """
                INSERT INTO external_champion_predictions (
                    source_key, snapshot_date, team, champion_prob, source_url,
                    data_quality, ingested_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_key, snapshot_date, team) DO UPDATE SET
                    champion_prob=excluded.champion_prob,
                    source_url=excluded.source_url,
                    data_quality=excluded.data_quality,
                    ingested_at=excluded.ingested_at
                """,
                values,
            )
        else:
            conn.execute(
                """
                INSERT INTO external_champion_predictions (
                    source_key, snapshot_date, team, champion_prob, source_url,
                    data_quality, ingested_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_key, snapshot_date, team) DO NOTHING
                """,
                values,
            )
        count += 1
    current = conn.execute(
        "SELECT last_sync_status FROM prediction_sources WHERE source_key = ?",
        (source_key,),
    ).fetchone()
    current_status = current[0] if current else None
    can_update_status = (
        replace
        or current_status is None
        or current_status == "not_synced"
        or str(current_status).startswith("seeded")
        or str(current_status).startswith("manual")
    )
    if can_update_status:
        conn.execute(
            """
            UPDATE prediction_sources
            SET snapshot_date = ?, last_sync_at = ?, last_sync_status = ?
            WHERE source_key = ?
            """,
            (snapshot_date, ingested_at, data_quality, source_key),
        )
    return count


def seed_known_snapshots(conn: sqlite3.Connection) -> int:
    inserted = 0
    for source_key, snapshot in STATIC_CHAMPION_SNAPSHOTS.items():
        inserted += upsert_champion_snapshot(
            conn,
            source_key,
            snapshot["snapshot_date"],
            snapshot["probs"],
            snapshot["data_quality"],
            replace=False,
        )
    return inserted


def ensure_default_data(conn: sqlite3.Connection) -> None:
    ensure_schema(conn)
    seed_source_catalog(conn)
    seed_known_snapshots(conn)
    conn.commit()


def _html_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    return soup.get_text("\n")


def parse_leadafrik_champion_probs(html: str) -> dict[str, float]:
    text = re.sub(r"\s+", " ", _html_text(html))
    out = {}
    for team, pct in re.findall(r"#\d+\s+([A-Z][A-Za-z .&-]+?)\s+(\d+(?:\.\d+)?)%\s+to win", text):
        out[normalize_team_name(team.strip())] = float(pct) / 100.0
    return out


def parse_zeileis_champion_probs(html: str) -> dict[str, float]:
    text = re.sub(r"\s+", " ", _html_text(html))
    out = {}
    first = re.search(r"Spain.*?winning probability of (\d+(?:\.\d+)?)%", text, re.I)
    if first:
        out["Spain"] = float(first.group(1)) / 100.0
    both = re.search(r"England and France, both with (\d+(?:\.\d+)?)%", text, re.I)
    if both:
        value = float(both.group(1)) / 100.0
        out["England"] = value
        out["France"] = value
    germany = re.search(r"Germany with (\d+(?:\.\d+)?)%", text, re.I)
    if germany:
        out["Germany"] = float(germany.group(1)) / 100.0
    return out


def fetch_public_html(url: str, timeout: int = 20) -> str:
    response = requests.get(url, timeout=timeout, headers={"User-Agent": "2026FIFA-source-sync/1.0"})
    response.raise_for_status()
    return response.text


def try_live_sync(conn: sqlite3.Connection) -> dict[str, str]:
    results = {}
    live_parsers = {
        "leadafrik": parse_leadafrik_champion_probs,
        "zeileis_groll": parse_zeileis_champion_probs,
    }
    for source_key, parser in live_parsers.items():
        source = next(item for item in SOURCE_CATALOG if item["source_key"] == source_key)
        try:
            probs = parser(fetch_public_html(source["source_url"]))
            if probs:
                upsert_champion_snapshot(
                    conn,
                    source_key,
                    source["snapshot_date"] or datetime.now().strftime("%Y-%m-%d"),
                    probs,
                    "live_html",
                )
                results[source_key] = f"live_html:{len(probs)}"
            else:
                results[source_key] = "no_values_found"
        except Exception as exc:
            results[source_key] = type(exc).__name__
    conn.commit()
    return results


def load_sources(conn: sqlite3.Connection) -> list[dict]:
    ensure_schema(conn)
    conn.row_factory = sqlite3.Row
    return [
        dict(row)
        for row in conn.execute(
            """
            SELECT *
            FROM prediction_sources
            ORDER BY
                CASE sync_mode
                    WHEN 'auto' THEN 1
                    WHEN 'partial_pdf' THEN 2
                    WHEN 'manual_snapshot' THEN 3
                    ELSE 4
                END,
                source_name
            """
        )
    ]


def load_champion_consensus(conn: sqlite3.Connection, limit: int = 12) -> list[dict]:
    ensure_schema(conn)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT
            e.team,
            AVG(e.champion_prob) AS avg_prob,
            MIN(e.champion_prob) AS min_prob,
            MAX(e.champion_prob) AS max_prob,
            COUNT(DISTINCT e.source_key) AS source_count,
            GROUP_CONCAT(s.source_name, ', ') AS sources
        FROM external_champion_predictions e
        JOIN prediction_sources s ON s.source_key = e.source_key
        GROUP BY e.team
        ORDER BY avg_prob DESC, source_count DESC, e.team ASC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def load_external_context(conn: sqlite3.Connection, limit: int = 12) -> tuple[list[dict], list[dict]]:
    ensure_default_data(conn)
    return load_sources(conn), load_champion_consensus(conn, limit=limit)


def sync_external_predictions(db_path: str = DB_PATH, fetch_live: bool = True) -> dict[str, str]:
    with sqlite3.connect(db_path) as conn:
        ensure_default_data(conn)
        if fetch_live:
            return try_live_sync(conn)
    return {"seeded": "ok"}


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sync external World Cup prediction sources.")
    parser.add_argument("--db", default=DB_PATH)
    parser.add_argument("--no-live", action="store_true", help="Only seed known public snapshots.")
    args = parser.parse_args(list(argv) if argv is not None else None)
    results = sync_external_predictions(args.db, fetch_live=not args.no_live)
    for source_key, status in sorted(results.items()):
        print(f"{source_key}: {status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
