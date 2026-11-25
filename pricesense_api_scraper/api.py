"""PriceSense API + single-server static web frontend.

Start from the repository root with:
    python -m uvicorn pricesense_api_scraper.api:app --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

from functools import lru_cache
from io import BytesIO
import json
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query, UploadFile, File
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from forecast_engine import prepare_data, to_daily_series, run_forecasting
from adaptive_forecaster import MODEL_NAME

BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent
WEB_DIR = ROOT_DIR / "frontend"
DATA_DIR = BASE_DIR / "data"
MAX_UPLOAD_BYTES = 10 * 1024 * 1024

app = FastAPI(
    title="PriceSense API",
    description="PriceSense retail price history, forecasting and web interface.",
    version="2.3.0",
)
app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


@lru_cache(maxsize=2)
def load_json(filename: str):
    if filename not in {"products.json", "price_history.json"}:
        raise HTTPException(status_code=400, detail="Unknown dataset")
    try:
        with (DATA_DIR / filename).open("r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"Could not load {filename}") from exc


@lru_cache(maxsize=1)
def default_data():
    return prepare_data(pd.DataFrame.from_records(load_json("price_history.json")))


def make_catalog(data: pd.DataFrame, source: str):
    products = (data.drop_duplicates(subset=["product_id"])
                .sort_values("product_name")[["product_id", "product_name"] +
                 (["category"] if "category" in data.columns else [])])
    # Avoid null/NaN values in serialized JSON.
    items = []
    for row in products.to_dict(orient="records"):
        items.append({k: (str(v) if pd.notna(v) else "Uncategorized") for k, v in row.items()})
    return {
        "source": source,
        "synthetic": source == "PriceSense demo dataset",
        "products": items,
        "overview": {
            "observations": int(len(data)),
            "products": int(data["product_id"].nunique()),
            "categories": int(data["category"].nunique()) if "category" in data.columns else None,
            "date_start": data["date"].min().strftime("%Y-%m-%d"),
            "date_end": data["date"].max().strftime("%Y-%m-%d"),
        },
    }


def assemble_forecast(data: pd.DataFrame, product_id: str, horizon: int, source: str):
    selected = data[data["product_id"].str.lower() == product_id.lower()].copy()
    if selected.empty:
        raise HTTPException(status_code=404, detail="Product not found in the selected dataset")
    aggregates = {"product_name": "last", "price": "mean"}
    if "category" in selected.columns:
        aggregates["category"] = "last"
    if "discount_percent" in selected.columns:
        aggregates["discount_percent"] = "mean"
    selected = selected.groupby("date", as_index=False).agg(aggregates).sort_values("date")
    if len(selected) < 5:
        raise HTTPException(status_code=422, detail="Select a product with at least five distinct price dates")
    daily = to_daily_series(selected)
    try:
        result = run_forecasting(daily, horizon)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    history = [{"date": date.strftime("%Y-%m-%d"), "price": float(price)}
               for date, price in zip(selected["date"], selected["price"])]
    latest = float(selected["price"].iloc[-1])
    latest_date = selected["date"].max()
    future_dates = pd.date_range(latest_date + pd.Timedelta(days=1), periods=horizon, freq="D")

    def forecast_points(values):
        return [{"date": date.strftime("%Y-%m-%d"), "price": float(value)}
                for date, value in zip(future_dates, values)]

    events = result["sale_windows"]
    pct = selected["price"].pct_change().dropna()
    metrics = []
    for row in result["metrics"].to_dict(orient="records"):
        metrics.append({
            "name": row["Model"],
            "mae": float(row["MAE (₹)"]),
            "rmse": float(row["RMSE (₹)"]),
            "mape": float(row["MAPE (%)"]),
            "r2": float(row["R²"]) if row["R²"] is not None and pd.notna(row["R²"]) else None,
            "weight": float(row["Weight"]),
        })

    return {
        "source": source,
        "synthetic": source == "PriceSense demo dataset",
        "product": {
            "id": product_id.upper(),
            "name": str(selected["product_name"].iloc[-1]),
            "category": str(selected["category"].iloc[-1]) if "category" in selected.columns else "Uncategorized",
            "latest_price": latest,
            "latest_date": latest_date.strftime("%Y-%m-%d"),
            "min_price": float(selected["price"].min()),
            "max_price": float(selected["price"].max()),
            "mean_price": float(selected["price"].mean()),
            "volatility_pct": float(pct.std() * 100) if len(pct) > 1 else None,
            "observations": len(selected),
            "daily_observations": len(daily),
        },
        "horizon": horizon,
        "history": history,
        "forecast": forecast_points(result["ensemble"]),
        "interval": [
            {"date": date.strftime("%Y-%m-%d"), "lower": float(lo), "upper": float(hi)}
            for date, lo, hi in zip(future_dates, result["lower"], result["upper"])
        ],
        "models": {name: forecast_points(vals) for name, vals in result["future"].items()},
        "metrics": metrics,
        "weights": {name: float(weight) for name, weight in result["weights"].items()},
        "deployment_weights": {name: float(weight) for name, weight in result["deployment_weights"].items()},
        "skipped": result["skipped"],
        "adaptive": {
            "available": MODEL_NAME in result["future"],
            "name": MODEL_NAME,
            "windows": events,
            "calendar_type": "Learned from repeated historical discounts, not confirmed promotions",
            "sale_effect_pct": [float(v) for v in result["sale_effect_pct"]],
            "regular_forecast": forecast_points(result["regular_forecast"]),
        },
        "evaluation": {
            "test_days": result["test_days"],
            "folds": result["folds"],
            "test_start": result["test_start"].strftime("%Y-%m-%d"),
            "test_end": result["test_end"].strftime("%Y-%m-%d"),
            "best_model": metrics[0]["name"],
        },
        "summary": {
            "next_day": float(result["ensemble"][0]),
            "horizon_price": float(result["ensemble"][-1]),
            "next_change_pct": float((result["ensemble"][0] / latest - 1) * 100),
            "horizon_change_pct": float((result["ensemble"][-1] / latest - 1) * 100),
            "lowest_forecast": float(np.min(result["ensemble"])),
            "highest_forecast": float(np.max(result["ensemble"])),
            "range_last_day": [float(result["lower"][-1]), float(result["upper"][-1])],
        },
    }


def read_uploaded_file(contents: bytes, filename: str | None):
    if not filename or not filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Please upload a CSV file")
    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="CSV file must be no larger than 10 MB")
    if not contents:
        raise HTTPException(status_code=400, detail="CSV file is empty")
    try:
        return prepare_data(pd.read_csv(BytesIO(contents)))
    except (pd.errors.ParserError, UnicodeError, ValueError, pd.errors.EmptyDataError) as exc:
        raise HTTPException(status_code=422, detail=f"Invalid CSV: {exc}") from exc


@app.get("/", include_in_schema=False)
def dashboard():
    return FileResponse(WEB_DIR / "index.html")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/products")
def get_products():
    products = load_json("products.json")
    return {"count": len(products), "products": products}


@app.get("/prices")
def get_prices(product_id: str | None = Query(default=None)):
    records = load_json("price_history.json")
    if product_id:
        records = [r for r in records if r["product_id"].lower() == product_id.lower()]
    return {"count": len(records), "records": records}


@app.get("/prices/{product_id}")
def get_product_prices(product_id: str):
    records = [r for r in load_json("price_history.json")
               if r["product_id"].lower() == product_id.lower()]
    if not records:
        raise HTTPException(status_code=404, detail=f"No price records found for {product_id}")
    return {"product_id": product_id.upper(), "count": len(records), "records": records}


@app.get("/api/info")
def api_info():
    return {"message": "PriceSense API is running", "documentation": "/docs"}


@app.get("/api/catalog")
def catalog():
    return make_catalog(default_data(), "PriceSense demo dataset")


@app.get("/api/forecast")
def forecast(product_id: str = Query(...), horizon: int = Query(7, ge=1, le=30)):
    return cached_default_forecast(product_id.upper(), horizon)


@lru_cache(maxsize=128)
def cached_default_forecast(product_id: str, horizon: int):
    return assemble_forecast(default_data(), product_id, horizon, "PriceSense demo dataset")


@app.post("/api/upload/preview")
async def upload_preview(file: UploadFile = File(...)):
    data = read_uploaded_file(await file.read(MAX_UPLOAD_BYTES + 1), file.filename)
    return make_catalog(data, "Uploaded CSV")


@app.post("/api/forecast-upload")
async def forecast_upload(file: UploadFile = File(...),
                          product_id: str = Query(...), horizon: int = Query(7, ge=1, le=30)):
    data = read_uploaded_file(await file.read(MAX_UPLOAD_BYTES + 1), file.filename)
    return assemble_forecast(data, product_id, horizon, "Uploaded CSV")
