"""Oracle tests for the causal-inference engine.

These validate the estimators the gold-standard way: plant a KNOWN effect in a
synthetic series and assert the engine recovers it, and confirm a no-effect
negative control is NOT flagged. Pure-Python (no database), deterministic via
fixed RNG seeds — the strongest, most autonomy-friendly proof of correctness.
"""

from __future__ import annotations

import numpy as np
import statsmodels.api as sm

from ingest.analysis.causal import (
    _design,
    _post_from_cut,
    did_estimate,
    fit_its,
    hac_maxlags,
    permutation_pvalue,
)


def _ar1(n: int, *, phi: float, sigma: float, seed: int) -> np.ndarray:
    """Autocorrelated (AR(1)) noise — the realistic case for daily physiology."""
    rng = np.random.default_rng(seed)
    e = rng.normal(0.0, sigma, n)
    y = np.zeros(n)
    for i in range(1, n):
        y[i] = phi * y[i - 1] + e[i]
    return y


def test_its_recovers_planted_level_step() -> None:
    n, cut, true_step = 60, 30, -5.0
    rng = np.random.default_rng(42)
    y = 60.0 + rng.normal(0.0, 1.0, n)
    y[cut:] += true_step
    post = _post_from_cut(n, cut)

    res = fit_its(y, post)
    assert abs(res.level_change - true_step) < 1.5, res.level_change
    assert res.hac_p_value < 0.05
    assert res.level_ci_low <= true_step <= res.level_ci_high
    assert res.n_pre == cut and res.n_post == n - cut


def test_its_recovers_planted_slope_change() -> None:
    n, cut, true_slope = 80, 40, 0.4
    rng = np.random.default_rng(7)
    t = np.arange(n, dtype=float)
    y = 50.0 + 0.0 * t + rng.normal(0.0, 0.8, n)
    y[cut:] += true_slope * (t[cut:] - cut)  # post-cutoff ramp
    post = _post_from_cut(n, cut)

    res = fit_its(y, post)
    assert abs(res.slope_change - true_slope) < 0.2, res.slope_change


def test_permutation_flags_real_effect() -> None:
    n, cut = 60, 30
    rng = np.random.default_rng(1)
    y = 60.0 + rng.normal(0.0, 1.0, n)
    y[cut:] += -5.0
    p = permutation_pvalue(y, _post_from_cut(n, cut), seed=0)
    assert p < 0.05, p


def test_permutation_negative_control_is_not_significant() -> None:
    """No planted effect -> the cutoff is no more 'special' than any other, so
    the placebo p must NOT be significant; a planted effect on the same series
    must be. This is the false-positive guard (the relative claim is the robust
    one at n~60)."""
    n, cut = 60, 30
    rng = np.random.default_rng(20)
    flat = 60.0 + rng.normal(0.0, 1.0, n)  # iid noise, NO step
    p_null = permutation_pvalue(flat, _post_from_cut(n, cut), seed=0)

    real = flat.copy()
    real[cut:] += -5.0
    p_real = permutation_pvalue(real, _post_from_cut(n, cut), seed=0)

    assert p_real < 0.05 <= p_null, (p_real, p_null)  # real significant, null not
    assert p_null > 10 * p_real  # null clearly weaker than a true effect


def test_hac_se_differs_from_naive_ols() -> None:
    """On autocorrelated data, the HAC standard error must differ from the naive
    OLS SE — proof the Newey-West correction is actually doing something."""
    n, cut = 80, 40
    y = 55.0 + _ar1(n, phi=0.7, sigma=1.0, seed=11)
    post = _post_from_cut(n, cut)
    x = _design(n, post)
    ols = sm.OLS(y, x).fit()
    hac = sm.OLS(y, x).fit(cov_type="HAC", cov_kwds={"maxlags": hac_maxlags(n)})
    rel_diff = abs(hac.bse[2] - ols.bse[2]) / ols.bse[2]
    assert rel_diff > 0.05, rel_diff


def test_did_estimate_recovers_treated_minus_control() -> None:
    n, cut = 40, 20
    post = _post_from_cut(n, cut)
    treated = np.full(n, 60.0)
    treated[cut:] += -4.0  # treated drops 4
    control = np.full(n, 60.0)
    control[cut:] += -1.0  # control drifts 1 (shared trend)
    did = did_estimate(treated, control, post)
    assert abs(did - (-3.0)) < 1e-6, did  # -4 - (-1) = -3
