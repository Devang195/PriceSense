"""PriceSense forecasting engine.

The statistical and ML algorithms and independent holdout methodology are
ported from the original implementation, with the custom PAF model added.
Every model trains on log-prices and returns log-price forecasts.
"""
from __future__ import annotations

import warnings
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from statsmodels.tsa.holtwinters import ExponentialSmoothing
from statsmodels.tsa.arima.model import ARIMA
from adaptive_forecaster import adaptive_baseline, learn_sales, MODEL_NAME

REQUIRED_COLUMNS = {"product_id", "product_name", "date", "price"}
MIN_TS_TRAIN = 6


def prepare_data(raw: pd.DataFrame) -> pd.DataFrame:
    missing = REQUIRED_COLUMNS - set(raw.columns)
    if missing:
        raise ValueError("Missing required columns: " + ", ".join(sorted(missing)))

    data = raw.copy()
    data["product_id"] = data["product_id"].astype("string").str.strip()
    data["product_name"] = data["product_name"].astype("string").str.strip()
    data["date"] = pd.to_datetime(data["date"], errors="coerce").dt.normalize()
    data["price"] = pd.to_numeric(data["price"], errors="coerce")
    data = data.dropna(subset=["product_id", "product_name", "date", "price"])
    data = data[(data["product_id"] != "") & (data["product_name"] != "")
                & (data["price"] > 0) & np.isfinite(data["price"])]
    data = data.sort_values("date").drop_duplicates(subset=["product_id", "date"], keep="last")
    if data.empty:
        raise ValueError("No valid price records were found in the dataset.")
    return data.sort_values(["product_id", "date"]).reset_index(drop=True)


def to_daily_series(product: pd.DataFrame) -> pd.Series:
    """Forward fill missing dates; do not interpolate using future observations."""
    s = product.set_index("date")["price"].astype(float)
    full_index = pd.date_range(s.index.min(), s.index.max(), freq="D")
    return s.reindex(full_index).ffill()


def _future_dates(dates: pd.DatetimeIndex, steps: int) -> pd.DatetimeIndex:
    return pd.date_range(dates[-1] + pd.Timedelta(days=1), periods=steps, freq="D")


def _naive(train, dates, steps):
    return np.repeat(train[-1], steps)


def _holt(train, dates, steps):
    if len(train) < MIN_TS_TRAIN:
        raise ValueError(f"needs at least {MIN_TS_TRAIN} training days")
    fit = ExponentialSmoothing(
        train, trend="add", damped_trend=True, initialization_method="estimated"
    ).fit()
    return np.asarray(fit.forecast(steps))


def _holt_winters(train, dates, steps):
    if len(train) < 21:
        raise ValueError("needs at least 21 training days for weekly seasonality")
    fit = ExponentialSmoothing(
        train, trend="add", damped_trend=True, seasonal="add",
        seasonal_periods=7, initialization_method="estimated"
    ).fit()
    return np.asarray(fit.forecast(steps))


def _arima(train, dates, steps):
    if len(train) < MIN_TS_TRAIN:
        raise ValueError(f"needs at least {MIN_TS_TRAIN} training days")
    best, best_aic = None, np.inf
    for order in [(1, 1, 0), (0, 1, 1), (1, 1, 1), (2, 1, 1)]:
        try:
            fit = ARIMA(train, order=order).fit()
            if np.isfinite(fit.aic) and fit.aic < best_aic:
                best, best_aic = fit, fit.aic
        except Exception:
            continue
    if best is None:
        raise ValueError("no ARIMA order could be fitted")
    return np.asarray(best.forecast(steps=steps))


def _gb_row(hist, dow):
    diffs = np.diff(hist[-8:])
    return np.concatenate([
        diffs,
        [hist[-1] - hist[-7:].mean(), hist[-1] - hist[-28:].mean(), dow],
    ])


def _gradient_boosting(train, dates, steps):
    if len(train) < 24:
        raise ValueError("needs at least 24 training days")
    X, y = [], []
    for t in range(8, len(train)):
        X.append(_gb_row(train[:t], dates[t].dayofweek))
        y.append(train[t] - train[t - 1])
    model = GradientBoostingRegressor(
        n_estimators=150, max_depth=2, learning_rate=0.05,
        subsample=0.8, random_state=42,
    ).fit(np.array(X), np.array(y))

    hist = list(train)
    out = []
    for d in _future_dates(dates, steps):
        step = model.predict(_gb_row(np.array(hist), d.dayofweek).reshape(1, -1))[0]
        hist.append(hist[-1] + step)
        out.append(hist[-1])
    return np.array(out)


MODELS = {
    "Naive (last price)": _naive,
    "Holt's Trend": _holt,
    "Seasonal Holt-Winters": _holt_winters,
    "ARIMA": _arima,
    "Gradient Boosting": _gradient_boosting,
    MODEL_NAME: adaptive_baseline,
}
BASELINE = "Naive (last price)"


def _scores(actual, pred):
    mae = mean_absolute_error(actual, pred)
    rmse = float(np.sqrt(mean_squared_error(actual, pred)))
    mape = float(np.mean(np.abs((actual - pred) / actual)) * 100)
    r2 = r2_score(actual, pred) if len(actual) >= 2 and np.unique(actual).size > 1 else None
    return mae, rmse, mape, r2


def run_forecasting(daily: pd.Series, horizon: int):
    if not 1 <= horizon <= 30:
        raise ValueError("Forecast horizon must be between 1 and 30 days")
    price = daily.to_numpy(dtype=float)
    if len(price) < 5:
        raise ValueError("At least five dated price observations are required")
    logp = np.log(price)
    dates = daily.index
    n = len(logp)

    # Evaluation: weights calibrated only on origins before the final holdout.
    L = max(2, min(14, int(n * 0.2)))
    test_origin = n - L
    step = max(1, L // 2)
    origins = sorted({o for o in (test_origin - L - 2 * step,
                                  test_origin - L - step,
                                  test_origin - L) if o >= 1})
    if not origins:
        raise ValueError("Not enough observations for chronological calibration")
    calibration_actuals = np.concatenate([price[o:o + L] for o in origins])
    actuals = price[test_origin:]

    # Learn events at each origin using its historical prefix only.
    # Advanced models predict regular prices, then receive the event effect once.
    event_cache = {}
    def events_at(origin, steps):
        key = (origin, steps)
        if key not in event_cache:
            event_cache[key] = learn_sales(logp[:origin], dates[:origin], steps)
        return event_cache[key]

    def forecast_at(fn, origin, steps):
        train = logp[:origin]
        lo, hi = train.min() - 1.0, train.max() + 1.0
        if fn is _naive:
            prediction = np.exp(np.clip(fn(train, dates[:origin], steps), lo, hi))
        else:
            historical_effect, future_effect, _ = events_at(origin, steps)
            regular = train - historical_effect
            prediction = np.exp(np.clip(fn(regular, dates[:origin], steps) + future_effect, lo, hi))
        if len(prediction) != steps or not np.all(np.isfinite(prediction)):
            raise ValueError("produced invalid forecasts")
        return prediction

    calibration, backtest, future, skipped = {}, {}, {}, {}
    for name, fn in MODELS.items():
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                preds = [forecast_at(fn, o, L) for o in origins]
                test_pred = forecast_at(fn, test_origin, L)
            calibration[name] = np.concatenate(preds)
            backtest[name] = test_pred
        except Exception as exc:
            skipped[name] = str(exc)

    # Preserve original inverse squared MAE and naive-baseline behaviour.
    members = [m for m in backtest if m != BASELINE]
    if members:
        maes = np.array([mean_absolute_error(calibration_actuals, calibration[m]) for m in members])
        raw_w = 1.0 / (maes ** 2 + 1e-9)
        weights = dict(zip(members, raw_w / raw_w.sum()))
        ens_bt = sum(weights[m] * backtest[m] for m in members)
        backtest["Weighted Ensemble"] = ens_bt
    elif BASELINE in backtest:
        weights = {}
        ens_bt = backtest[BASELINE].copy()
        backtest["Weighted Ensemble (Naive fallback)"] = ens_bt
    else:
        raise ValueError("No forecasting model could be fitted")

    for name in calibration:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                future[name] = forecast_at(MODELS[name], n, horizon)
        except Exception as exc:
            skipped[name] = f"Final refit: {exc}"
    deployment_weights = {m: w for m, w in weights.items() if m in future}
    weight_sum = sum(deployment_weights.values())
    if weight_sum > 0:
        deployment_weights = {m: w / weight_sum for m, w in deployment_weights.items()}
        ens_future = sum(w * future[m] for m, w in deployment_weights.items())
    else:
        deployment_weights = {}
        if BASELINE not in future:
            raise ValueError("No model is available for future forecasting")
        ens_future = future[BASELINE].copy()

    rows = []
    for name, pred in backtest.items():
        mae, rmse, mape, r2 = _scores(actuals, pred)
        rows.append({
            "Model": name, "MAE (₹)": mae, "RMSE (₹)": rmse,
            "MAPE (%)": mape, "R²": r2, "Weight": weights.get(name, 0.0) * 100,
        })
    metrics_df = pd.DataFrame(rows).sort_values("MAE (₹)").reset_index(drop=True)

    ens_rmse = float(np.sqrt(mean_squared_error(actuals, ens_bt)))
    h = np.arange(1, horizon + 1)
    sigma = ens_rmse * np.sqrt(h / ((L + 1) / 2))
    lower = np.maximum(ens_future - 1.28 * sigma, 0)
    upper = ens_future + 1.28 * sigma

    _, event_effect, event_windows = events_at(n, horizon) if deployment_weights else (None, np.zeros(horizon), [])
    return {
        "sale_windows": event_windows, "sale_effect_pct": 100 * (1 - np.exp(event_effect)),
        "regular_forecast": ens_future / np.exp(event_effect),
        "metrics": metrics_df, "future": future, "ensemble": ens_future,
        "lower": lower, "upper": upper, "weights": weights, "skipped": skipped,
        "test_days": L, "folds": len(origins),
        "test_start": dates[test_origin], "test_end": dates[-1],
        "deployment_weights": deployment_weights,
    }
