"""
model_config.py — single source of truth for every tunable prediction parameter.

Why this exists
---------------
Previously all model constants (Elo K, home advantage, Dixon-Coles rho, ensemble
weights, feature weights ...) were hard-coded inside sync_fifa.py with no way to
measure or improve them. This module centralises them so that:

  * backtest.py can override them in-process and grid/coordinate-search for the
    values that minimise the Ranked Probability Score on ~50k historical
    internationals, and
  * the best values found are persisted to `calibrated_params.json` and loaded
    automatically here at import time.

Defaults below reproduce the original hard-coded behaviour, EXCEPT where a change
is a well-established, low-risk accuracy win (Elo margin-of-victory ON, dead
sentiment feature disabled). Anything calibrated from data lands in the JSON file
and overlays these defaults.
"""

import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
CALIBRATED_PATH = os.path.join(_HERE, 'calibrated_params.json')


class ModelConfig:
    def __init__(self):
        # ---- Elo (Model A) ----
        self.ELO_K = 60.0              # base K-factor for World Cup matches
        self.ELO_MOV_ENABLED = True    # #3 scale K by goal-difference (margin of victory)
        self.HOME_ADV_ELO = 70.0       # Elo-equivalent host-nation home boost
        self.HOME_ADV_GOALS = 0.30     # goal-shift fed into the Pi model on host games
        self.RANK_WEIGHT = 4.0         # FIFA-rank-diff contribution to effective Elo

        # ---- Poisson goal model / lambda scaling (#7 fixes the "always 1-1" issue) ----
        self.LAMBDA_BASE_HOME = 1.45   # baseline expected home goals (hist. ~1.5)
        self.LAMBDA_BASE_AWAY = 1.15   # baseline expected away goals (hist. ~1.1)
        self.LAMBDA_DIVISOR = 1000.0   # spread of strength-diff -> lambda

        # ---- Dixon-Coles (Model D) ----
        self.RHO = -0.12               # low-score correlation correction

        # ---- External-intel feature weights, in Elo points (#5) ----
        self.W_XG = 15.0               # FBref expected-goal-diff
        self.W_SENTIMENT = 0.0         # DISABLED: scraper currently yields all-zero; was unvalidated noise
        self.W_INJURY = 12.0           # squad injuries (subtracted)

        # ---- Draw calibration (#2): multiplicative inflation of draw mass, then renormalise ----
        self.DRAW_INFLATION = 1.0      # 1.0 = no change; calibrated upward to fix 0/104 draws
        # Knockout fixtures are systematically cagier over 90 minutes (the target
        # is the 90' result; ET/pens are out of scope for the model): historical
        # WC knockout 90' draw rates run ~27–31% (2018 ≈27%, 2022 ≈31%) and this
        # tournament's R32 came in at 31% (5/16), vs the model's ~24% average
        # knockout draw. Applied ON TOP of DRAW_INFLATION for knockout games only.
        # Not fit by backtest.py (its dataset has no round labels) — a documented
        # prior, validated live via the site's rolling accuracy tracking.
        self.KO_DRAW_INFLATION = 1.15

        # ---- Ensemble fusion weights [elo, pi, berrar, dixon_coles, opta] ----
        self.W_ENSEMBLE_OPTA = [0.22, 0.22, 0.18, 0.28, 0.10]
        self.W_ENSEMBLE_NOOPTA = [0.25, 0.25, 0.20, 0.30]

        # ---- Dynamic weighting by tournament completion (#4) ----
        # Early in the event trust the Opta/market prior; as matches complete and the
        # in-tournament ratings sharpen, shift weight onto the updated models.
        self.DYNAMIC_WEIGHTS = True
        self.W_EARLY = [0.18, 0.18, 0.14, 0.20, 0.30]   # completion ratio = 0
        self.W_LATE = [0.26, 0.24, 0.22, 0.28, 0.00]    # completion ratio = 1

        self.load(CALIBRATED_PATH)

    def load(self, path):
        """Overlay persisted calibration results, if present."""
        try:
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                for k, v in data.items():
                    if hasattr(self, k):
                        setattr(self, k, v)
        except Exception:
            pass
        return self

    def as_dict(self):
        return {k: v for k, v in self.__dict__.items()}


# Module-level singleton read by sync_fifa.py's engine functions.
CFG = ModelConfig()
