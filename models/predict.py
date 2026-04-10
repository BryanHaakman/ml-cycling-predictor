"""
Prediction and Kelly Criterion staking advice.
"""

import os
import json
import pickle
import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np

from data.scraper import get_db, DB_PATH
from features.pipeline import build_feature_vector, build_feature_vector_manual, get_all_feature_names

log = logging.getLogger(__name__)

MODELS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "models", "trained")


@dataclass
class KellyResult:
    """Result of Kelly Criterion calculation."""
    edge: float            # Model probability - implied probability
    kelly_fraction: float  # Optimal fraction of bankroll to bet
    half_kelly: float      # Conservative: half Kelly (recommended)
    quarter_kelly: float   # Ultra-conservative: quarter Kelly
    expected_value: float  # Expected value per unit bet
    should_bet: bool       # Whether there's positive expected value

    def describe(self) -> str:
        if not self.should_bet:
            return "No value — model agrees with or favours the bookmaker's price."
        return (
            f"Edge: {self.edge:.1%} | "
            f"EV per £1: £{self.expected_value:.3f} | "
            f"Full Kelly: {self.kelly_fraction:.1%} of bankroll | "
            f"Half Kelly (rec.): {self.half_kelly:.1%} | "
            f"Quarter Kelly: {self.quarter_kelly:.1%}"
        )


def decimal_odds_to_implied_prob(decimal_odds: float) -> float:
    """Convert decimal odds (e.g. 2.50) to implied probability."""
    if decimal_odds <= 1.0:
        return 1.0
    return 1.0 / decimal_odds


def fractional_odds_to_decimal(fractional: str) -> float:
    """Convert fractional odds like '5/2' to decimal odds (3.50)."""
    parts = fractional.strip().split("/")
    if len(parts) == 2:
        return float(parts[0]) / float(parts[1]) + 1.0
    return float(fractional)


def american_odds_to_decimal(american: int) -> float:
    """Convert American odds (+150, -200) to decimal."""
    if american > 0:
        return american / 100.0 + 1.0
    else:
        return 100.0 / abs(american) + 1.0


def kelly_criterion(
    model_prob: float,
    decimal_odds: float,
    max_fraction: float = 0.20,
) -> KellyResult:
    """
    Calculate Kelly Criterion staking with confidence scaling.

    Kelly formula: f* = (bp - q) / b
    where:
        b = decimal_odds - 1 (net odds)
        p = model's estimated probability of winning
        q = 1 - p (probability of losing)

    Staking uses half Kelly (recommended) and quarter Kelly (conservative).
    max_fraction=0.20 means quarter Kelly is capped at 5% of bankroll.
    No confidence scaling — raw Kelly for maximum ROI.

    Args:
        model_prob: Model's predicted probability (0-1)
        decimal_odds: Bookmaker's decimal odds (e.g. 2.50)
        max_fraction: Cap on Kelly fraction to limit risk (default 0.20 → 5% max via quarter Kelly)

    Returns:
        KellyResult with staking advice
    """
    if decimal_odds <= 1.0:
        return KellyResult(0, 0, 0, 0, 0, False)

    b = decimal_odds - 1.0  # net profit per unit if winning
    p = model_prob
    q = 1.0 - p

    # Kelly fraction
    kelly_f = (b * p - q) / b

    # Expected value per unit bet
    ev = p * b - q  # = p * (odds - 1) - (1 - p)

    implied_prob = decimal_odds_to_implied_prob(decimal_odds)
    edge = model_prob - implied_prob

    if kelly_f <= 0:
        return KellyResult(
            edge=edge,
            kelly_fraction=0,
            half_kelly=0,
            quarter_kelly=0,
            expected_value=ev,
            should_bet=False,
        )

    # Cap Kelly to avoid over-betting
    kelly_f = min(kelly_f, max_fraction)

    scaled_half = kelly_f / 2
    scaled_quarter = kelly_f / 4

    return KellyResult(
        edge=edge,
        kelly_fraction=kelly_f,
        half_kelly=scaled_half,
        quarter_kelly=scaled_quarter,
        expected_value=ev,
        should_bet=True,
    )


@dataclass
class PredictionResult:
    """Full prediction output."""
    rider_a_name: str
    rider_b_name: str
    prob_a_wins: float
    prob_b_wins: float
    kelly_a: Optional[KellyResult]
    kelly_b: Optional[KellyResult]
    model_used: str
    feature_importances: Optional[dict]  # top contributing features


class Predictor:
    """Load trained model and make predictions."""

    def __init__(self, model_name: str = "CalibratedXGBoost", db_path: str = DB_PATH):
        self.db_path = db_path
        self.model_name = model_name
        self._load_model(model_name)

    def _load_model(self, model_name: str):
        with open(os.path.join(MODELS_DIR, "scaler.pkl"), "rb") as f:
            self.scaler = pickle.load(f)

        with open(os.path.join(MODELS_DIR, "feature_names.json"), "r") as f:
            self.feature_names = json.load(f)

        if model_name == "NeuralNetwork":
            import torch
            from models.neural_net import CyclingNet
            input_dim = len(self.feature_names)
            self.model = CyclingNet(input_dim)
            state = torch.load(
                os.path.join(MODELS_DIR, "neural_net.pt"),
                map_location="cpu", weights_only=True,
            )
            self.model.load_state_dict(state)
            self.model.eval()
        else:
            with open(os.path.join(MODELS_DIR, f"{model_name}.pkl"), "rb") as f:
                self.model = pickle.load(f)

    def predict(
        self,
        rider_a_url: str,
        rider_b_url: str,
        stage_url: str,
        odds_a: Optional[float] = None,
        odds_b: Optional[float] = None,
    ) -> PredictionResult:
        """
        Make a head-to-head prediction.

        Args:
            rider_a_url: PCS relative URL for rider A
            rider_b_url: PCS relative URL for rider B
            stage_url: PCS relative URL for the stage/race
            odds_a: Decimal odds for rider A winning the H2H (optional)
            odds_b: Decimal odds for rider B winning the H2H (optional)

        Returns:
            PredictionResult with probabilities and Kelly staking advice
        """
        conn = get_db(self.db_path)

        fv = build_feature_vector(conn, rider_a_url, rider_b_url, stage_url)
        if fv is None:
            conn.close()
            raise ValueError("Could not build features — check stage/rider URLs exist in cache")

        X = np.array([[fv.get(name, 0.0) for name in self.feature_names]])
        X_scaled = self.scaler.transform(X)

        if self.model_name == "NeuralNetwork":
            from models.neural_net import predict_neural_net
            prob_a = float(predict_neural_net(self.model, X_scaled)[0])
        else:
            prob_a = float(self.model.predict_proba(X_scaled)[0, 1])

        prob_b = 1.0 - prob_a

        # Get rider names
        rider_a = conn.execute(
            "SELECT name FROM riders WHERE url = ?", (rider_a_url,)
        ).fetchone()
        rider_b = conn.execute(
            "SELECT name FROM riders WHERE url = ?", (rider_b_url,)
        ).fetchone()
        conn.close()

        name_a = rider_a["name"] if rider_a else rider_a_url
        name_b = rider_b["name"] if rider_b else rider_b_url

        # Kelly calculations
        kelly_a = kelly_criterion(prob_a, odds_a) if odds_a else None
        kelly_b = kelly_criterion(prob_b, odds_b) if odds_b else None

        return PredictionResult(
            rider_a_name=name_a,
            rider_b_name=name_b,
            prob_a_wins=prob_a,
            prob_b_wins=prob_b,
            kelly_a=kelly_a,
            kelly_b=kelly_b,
            model_used=self.model_name,
            feature_importances=None,
        )

    def predict_manual(
        self,
        rider_a_url: str,
        rider_b_url: str,
        race_params: dict,
        odds_a: Optional[float] = None,
        odds_b: Optional[float] = None,
    ) -> PredictionResult:
        """
        Predict for an upcoming / manually-specified race.

        Args:
            rider_a_url: PCS relative URL for rider A
            rider_b_url: PCS relative URL for rider B
            race_params: Dict with keys distance, vertical_meters, profile_icon,
                         profile_score, is_one_day_race, stage_type, race_date,
                         race_base_url, etc.
            odds_a / odds_b: Decimal bookmaker odds (optional)
        """
        conn = get_db(self.db_path)

        fv = build_feature_vector_manual(conn, rider_a_url, rider_b_url, race_params)
        if fv is None:
            conn.close()
            raise ValueError("Could not build features for manual race parameters")

        X = np.array([[fv.get(name, 0.0) for name in self.feature_names]])
        X_scaled = self.scaler.transform(X)

        if self.model_name == "NeuralNetwork":
            from models.neural_net import predict_neural_net
            prob_a = float(predict_neural_net(self.model, X_scaled)[0])
        else:
            prob_a = float(self.model.predict_proba(X_scaled)[0, 1])

        prob_b = 1.0 - prob_a

        rider_a = conn.execute(
            "SELECT name FROM riders WHERE url = ?", (rider_a_url,)
        ).fetchone()
        rider_b = conn.execute(
            "SELECT name FROM riders WHERE url = ?", (rider_b_url,)
        ).fetchone()
        conn.close()

        name_a = rider_a["name"] if rider_a else rider_a_url
        name_b = rider_b["name"] if rider_b else rider_b_url

        kelly_a = kelly_criterion(prob_a, odds_a) if odds_a else None
        kelly_b = kelly_criterion(prob_b, odds_b) if odds_b else None

        return PredictionResult(
            rider_a_name=name_a,
            rider_b_name=name_b,
            prob_a_wins=prob_a,
            prob_b_wins=prob_b,
            kelly_a=kelly_a,
            kelly_b=kelly_b,
            model_used=self.model_name,
            feature_importances=None,
        )
