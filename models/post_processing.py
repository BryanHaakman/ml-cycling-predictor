"""
Probabilistic post-processing layer for H2H predictions.

Sits on top of XGBoost's raw P(A>B) and adjusts probabilities using:

1. **Variance-aware adjustment (σ)**: Widens probabilities toward 0.5
   when riders are volatile, using the Φ-framework.
2. **Bayesian uncertainty (τ)**: Shrinks toward 0.5 when we have
   limited data on a rider (epistemic uncertainty).
3. **Upset injection (ε-mixture)**: Blends with 0.5 to model
   irreducible race chaos (crashes, mechanicals, tactics).
4. **Extreme probability shrinkage**: Hard bounds to prevent
   overconfident predictions in a stochastic sport.
5. **Temperature scaling**: Learned calibration parameter on logits.

Mathematical framework:
    X_A ~ N(μ_A, σ_A)  (rider performance is stochastic)
    X_B ~ N(μ_B, σ_B)

    P(A > B) = Φ( (μ_A - μ_B) / √(σ_A² + σ_B² + τ_A² + τ_B²) )

    where σ = race-day variance, τ = epistemic uncertainty

Usage:
    from models.post_processing import ProbabilityAdjuster
    adjuster = ProbabilityAdjuster()
    p_adjusted = adjuster.adjust(p_raw, features_a, features_b, race_features)
"""

import numpy as np
from scipy.stats import norm
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AdjustmentConfig:
    """Configuration for probability post-processing."""

    # --- Variance-aware adjustment ---
    # Base σ for all riders (irreducible race randomness)
    sigma_base: float = 0.15
    # How much rider rank_stddev contributes to σ
    sigma_rider_weight: float = 0.008
    # How much course-type variance contributes
    sigma_course_weight: float = 0.005

    # --- Bayesian uncertainty ---
    # Smoothing constant κ: τ = 1/√(n_recent + κ)
    tau_kappa: float = 5.0
    # Scale for τ (controls maximum uncertainty for unknown riders)
    tau_scale: float = 0.20
    # Minimum recent races before τ starts shrinking
    tau_min_races: int = 3

    # --- Upset / chaos injection ---
    # Base chaos probability (irreducible upset rate)
    epsilon_base: float = 0.03
    # Additional chaos for one-day races (more random)
    epsilon_one_day_bonus: float = 0.02
    # Additional chaos for hilly/mountain stages (more crashes)
    epsilon_hilly_bonus: float = 0.01

    # --- Extreme probability shrinkage ---
    # Hard floor/ceiling on predictions
    prob_floor: float = 0.04
    prob_ceiling: float = 0.96

    # --- Temperature scaling ---
    # T > 1 softens predictions, T < 1 sharpens
    temperature: float = 1.0

    # --- Master switches ---
    use_variance_adjustment: bool = True
    use_bayesian_uncertainty: bool = True
    use_upset_injection: bool = True
    use_extreme_shrinkage: bool = True
    use_temperature: bool = True


@dataclass
class AdjustmentResult:
    """Detailed output from probability adjustment."""
    p_raw: float
    p_adjusted: float
    sigma_a: float
    sigma_b: float
    tau_a: float
    tau_b: float
    epsilon: float
    temperature: float
    adjustments_applied: list = field(default_factory=list)

    @property
    def total_uncertainty(self) -> float:
        """Combined uncertainty from all sources."""
        return np.sqrt(self.sigma_a**2 + self.sigma_b**2 +
                       self.tau_a**2 + self.tau_b**2)

    @property
    def confidence(self) -> float:
        """Confidence in the prediction (inverse of uncertainty)."""
        return 1.0 / (1.0 + self.total_uncertainty)

    def describe(self) -> str:
        """Human-readable summary of adjustments."""
        delta = self.p_adjusted - self.p_raw
        parts = [
            f"P(raw)={self.p_raw:.3f} → P(adj)={self.p_adjusted:.3f} "
            f"(Δ={delta:+.3f})",
            f"σ_A={self.sigma_a:.3f}, σ_B={self.sigma_b:.3f}",
            f"τ_A={self.tau_a:.3f}, τ_B={self.tau_b:.3f}",
            f"ε={self.epsilon:.3f}, T={self.temperature:.2f}",
            f"Total uncertainty={self.total_uncertainty:.3f}",
        ]
        return " | ".join(parts)


class ProbabilityAdjuster:
    """
    Post-processing layer that adjusts raw XGBoost probabilities.

    Applies a pipeline of adjustments:
    1. Temperature scaling (on logits)
    2. Variance-aware Φ-adjustment
    3. Bayesian uncertainty shrinkage
    4. Upset/chaos injection
    5. Extreme probability clipping
    """

    def __init__(self, config: Optional[AdjustmentConfig] = None):
        self.config = config or AdjustmentConfig()

    def estimate_sigma(self, rider_features: dict, race_features: dict) -> float:
        """
        Estimate race-day variance σ for a rider in a given race context.

        σ combines:
        - Base randomness (all riders have some)
        - Rider-specific volatility (from rank_stddev features)
        - Course-type volatility (mountains > flat)
        """
        c = self.config
        sigma = c.sigma_base

        # Rider volatility from rank stddev (use 90d if available, else career)
        rank_std_90d = rider_features.get("form_90d_rank_stddev", 25.0)
        rank_std_career = rider_features.get("career_rank_stddev", 25.0)

        # Use 90d if rider has recent races, else career
        n_90d = rider_features.get("form_90d_races", 0)
        rank_std = rank_std_90d if n_90d >= 3 else rank_std_career

        sigma += c.sigma_rider_weight * rank_std

        # Course-type volatility
        profile = race_features.get("race_profile_icon_num", 2)
        if profile >= 4:  # mountain
            course_std = rider_features.get("course_mountain_rank_stddev", 25.0)
        elif profile >= 2:  # hilly
            course_std = rider_features.get("course_hilly_rank_stddev", 25.0)
        else:  # flat
            course_std = rider_features.get("course_flat_rank_stddev", 25.0)

        sigma += c.sigma_course_weight * course_std

        return sigma

    def estimate_tau(self, rider_features: dict) -> float:
        """
        Estimate epistemic uncertainty τ for a rider.

        τ = scale / √(n_recent + κ)

        Riders with many recent results → low τ (we know them well)
        Riders with few results → high τ (uncertain estimate)
        """
        c = self.config

        # Use 90-day race count as primary signal, fall back to career
        n_recent = rider_features.get("form_90d_races", 0)
        n_career = rider_features.get("career_races", 0)

        # Blend: weight recent data more heavily
        n_effective = n_recent * 2 + min(n_career, 50) * 0.1

        if n_effective < c.tau_min_races:
            return c.tau_scale  # maximum uncertainty

        tau = c.tau_scale / np.sqrt(n_effective + c.tau_kappa)
        return tau

    def estimate_epsilon(self, race_features: dict) -> float:
        """
        Estimate race chaos probability ε.

        ε represents the probability of an outcome determined by
        factors outside the model (crashes, mechanicals, tactics,
        weather, illness).
        """
        c = self.config
        eps = c.epsilon_base

        # One-day races are more chaotic
        if race_features.get("race_is_one_day_race", 0) == 1:
            eps += c.epsilon_one_day_bonus

        # Mountain/hilly stages have more crashes
        profile = race_features.get("race_profile_icon_num", 2)
        if profile >= 2:  # hilly or mountain
            eps += c.epsilon_hilly_bonus

        return min(eps, 0.15)  # cap at 15%

    def _apply_temperature(self, p: float) -> float:
        """Apply temperature scaling to logits."""
        if not self.config.use_temperature or self.config.temperature == 1.0:
            return p

        # Convert to logit, scale, convert back
        p = np.clip(p, 1e-7, 1 - 1e-7)
        logit = np.log(p / (1 - p))
        logit_scaled = logit / self.config.temperature
        return 1.0 / (1.0 + np.exp(-logit_scaled))

    def _apply_variance_adjustment(self, p: float,
                                   sigma_a: float, sigma_b: float,
                                   tau_a: float, tau_b: float) -> float:
        """
        Apply Φ-based variance adjustment.

        Converts P(A>B) → estimate of μ_A - μ_B (signal strength),
        then re-evaluates under the full variance model:

        P_adj = Φ( Φ⁻¹(P_raw) / √(1 + σ_A² + σ_B² + τ_A² + τ_B²) )

        Intuition: If the raw model says P=0.80, that implies a certain
        strength gap. But if both riders are volatile (high σ) or we're
        uncertain about them (high τ), the *effective* probability should
        be closer to 0.50.
        """
        p_clipped = np.clip(p, 1e-7, 1 - 1e-7)

        # Φ⁻¹(P) gives the z-score (signal strength in standardised units)
        z = norm.ppf(p_clipped)

        # The denominator inflates with uncertainty, pulling z toward 0
        total_var = sigma_a**2 + sigma_b**2 + tau_a**2 + tau_b**2
        denominator = np.sqrt(1.0 + total_var)

        z_adjusted = z / denominator
        return float(norm.cdf(z_adjusted))

    def _apply_upset_injection(self, p: float, epsilon: float) -> float:
        """
        Apply ε-mixture for race chaos.

        P_final = (1 - ε) · P_model + ε · 0.5

        This pulls all predictions toward 0.5 by a small amount,
        reflecting the irreducible randomness in cycling.
        """
        return (1.0 - epsilon) * p + epsilon * 0.5

    def _apply_extreme_shrinkage(self, p: float) -> float:
        """Clip probabilities to [floor, ceiling]."""
        return np.clip(p, self.config.prob_floor, self.config.prob_ceiling)

    def adjust(self,
               p_raw: float,
               rider_a_features: dict,
               rider_b_features: dict,
               race_features: dict) -> AdjustmentResult:
        """
        Full probability adjustment pipeline.

        Args:
            p_raw: Raw XGBoost P(A > B)
            rider_a_features: Dict of rider A's features
            rider_b_features: Dict of rider B's features
            race_features: Dict of race-level features

        Returns:
            AdjustmentResult with adjusted probability and diagnostics
        """
        c = self.config
        p = p_raw
        adjustments = []

        # Estimate all uncertainty components
        sigma_a = self.estimate_sigma(rider_a_features, race_features)
        sigma_b = self.estimate_sigma(rider_b_features, race_features)
        tau_a = self.estimate_tau(rider_a_features)
        tau_b = self.estimate_tau(rider_b_features)
        epsilon = self.estimate_epsilon(race_features)

        # 1. Temperature scaling
        if c.use_temperature and c.temperature != 1.0:
            p = self._apply_temperature(p)
            adjustments.append("temperature")

        # 2. Variance + uncertainty adjustment (combined Φ)
        if c.use_variance_adjustment or c.use_bayesian_uncertainty:
            s_a = sigma_a if c.use_variance_adjustment else 0.0
            s_b = sigma_b if c.use_variance_adjustment else 0.0
            t_a = tau_a if c.use_bayesian_uncertainty else 0.0
            t_b = tau_b if c.use_bayesian_uncertainty else 0.0
            p = self._apply_variance_adjustment(p, s_a, s_b, t_a, t_b)
            adjustments.append("phi_adjustment")

        # 3. Upset injection
        if c.use_upset_injection:
            p = self._apply_upset_injection(p, epsilon)
            adjustments.append("upset_injection")

        # 4. Extreme shrinkage
        if c.use_extreme_shrinkage:
            p = self._apply_extreme_shrinkage(p)
            adjustments.append("extreme_shrinkage")

        return AdjustmentResult(
            p_raw=p_raw,
            p_adjusted=p,
            sigma_a=sigma_a,
            sigma_b=sigma_b,
            tau_a=tau_a,
            tau_b=tau_b,
            epsilon=epsilon,
            temperature=c.temperature,
            adjustments_applied=adjustments,
        )

    def adjust_batch(self,
                     p_raw: np.ndarray,
                     features_a: list[dict],
                     features_b: list[dict],
                     race_feats: list[dict]) -> np.ndarray:
        """Vectorised batch adjustment. Returns array of adjusted probabilities."""
        results = np.empty(len(p_raw))
        for i in range(len(p_raw)):
            result = self.adjust(p_raw[i], features_a[i], features_b[i], race_feats[i])
            results[i] = result.p_adjusted
        return results


def fit_temperature(y_true: np.ndarray, y_prob: np.ndarray,
                    lr: float = 0.01, max_iter: int = 1000) -> float:
    """
    Fit temperature parameter T by minimising NLL on a calibration set.

    log P_cal = log σ(logit(P_raw) / T)

    Uses simple gradient descent on a single scalar parameter.
    """
    y_true = np.asarray(y_true, dtype=float)
    y_prob = np.clip(np.asarray(y_prob, dtype=float), 1e-7, 1 - 1e-7)
    logits = np.log(y_prob / (1 - y_prob))

    T = 1.0
    best_T = 1.0
    best_nll = float("inf")

    for _ in range(max_iter):
        # Forward: P = σ(logit / T)
        scaled = logits / T
        p = 1.0 / (1.0 + np.exp(-scaled))
        p = np.clip(p, 1e-7, 1 - 1e-7)

        # NLL
        nll = -np.mean(y_true * np.log(p) + (1 - y_true) * np.log(1 - p))

        if nll < best_nll:
            best_nll = nll
            best_T = T

        # Gradient: dNLL/dT = -mean( (y - p) * logit / T² )
        grad = -np.mean((y_true - p) * logits / (T ** 2))
        T -= lr * grad
        T = max(0.1, min(T, 5.0))  # keep T in reasonable range

    return best_T


def fit_platt_scaling(y_true: np.ndarray, y_prob: np.ndarray):
    """
    Fit Platt scaling: P_cal = σ(a · logit(P_raw) + b).

    Returns (a, b) parameters.
    """
    from sklearn.linear_model import LogisticRegression

    y_prob = np.clip(y_prob, 1e-7, 1 - 1e-7)
    logits = np.log(y_prob / (1 - y_prob)).reshape(-1, 1)

    lr = LogisticRegression(C=1e10, solver="lbfgs", max_iter=5000)
    lr.fit(logits, y_true)

    a = float(lr.coef_[0, 0])
    b = float(lr.intercept_[0])
    return a, b


def apply_platt_scaling(y_prob: np.ndarray, a: float, b: float) -> np.ndarray:
    """Apply fitted Platt scaling."""
    y_prob = np.clip(y_prob, 1e-7, 1 - 1e-7)
    logits = np.log(y_prob / (1 - y_prob))
    return 1.0 / (1.0 + np.exp(-(a * logits + b)))


def fit_beta_calibration(y_true: np.ndarray, y_prob: np.ndarray):
    """
    Fit beta calibration: P_cal = σ(a·log(P) + b·log(1-P) + c).

    Returns (a, b, c) parameters. Handles asymmetric miscalibration.
    """
    from sklearn.linear_model import LogisticRegression

    y_prob = np.clip(y_prob, 1e-7, 1 - 1e-7)
    X = np.column_stack([np.log(y_prob), np.log(1 - y_prob)])

    lr = LogisticRegression(C=1e10, solver="lbfgs", max_iter=5000)
    lr.fit(X, y_true)

    a = float(lr.coef_[0, 0])
    b = float(lr.coef_[0, 1])
    c = float(lr.intercept_[0])
    return a, b, c


def apply_beta_calibration(y_prob: np.ndarray,
                           a: float, b: float, c: float) -> np.ndarray:
    """Apply fitted beta calibration."""
    y_prob = np.clip(y_prob, 1e-7, 1 - 1e-7)
    z = a * np.log(y_prob) + b * np.log(1 - y_prob) + c
    return 1.0 / (1.0 + np.exp(-z))
