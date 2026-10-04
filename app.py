from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from statsmodels.tsa.holtwinters import ExponentialSmoothing
from statsmodels.tsa.arima.model import ARIMA

BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = BASE_DIR / "data" / "price_history.csv"
REQUIRED_COLUMNS = {"product_id", "product_name", "date", "price"}

st.set_page_config(page_title="PriceSense", page_icon="📈", layout="wide")

@st.cache_data
def load_csv(file) -> pd.DataFrame:
    return pd.read_csv(file)


def prepare_data(raw: pd.DataFrame) -> pd.DataFrame:
    missing = REQUIRED_COLUMNS - set(raw.columns)
    if missing:
        raise ValueError("Missing required columns: " + ", ".join(sorted(missing)))

    data = raw.copy()
    data["product_id"] = data["product_id"].astype(str).str.strip()
    data["product_name"] = data["product_name"].astype(str).str.strip()
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    data["price"] = pd.to_numeric(data["price"], errors="coerce")
    data = data.dropna(subset=["product_id", "product_name", "date", "price"])
    data = data[(data["product_id"] != "") & (data["price"] > 0)]
    data = data.sort_values("date").drop_duplicates(
        subset=["product_id", "date"], keep="last"
    )
    if data.empty:
        raise ValueError("No valid price records were found in the dataset.")
    return data.sort_values(["product_id", "date"]).reset_index(drop=True)


def make_features(product_data: pd.DataFrame):
    start_date = product_data["date"].min()
    days = (product_data["date"] - start_date).dt.days.astype(float)
    return days.to_numpy().reshape(-1, 1), start_date


st.title("📈 PriceSense")
st.caption("Explore historical prices and estimate short-term price trends with a simple machine-learning baseline.")

with st.sidebar:
    st.header("Data source")
    uploaded_file = st.file_uploader("Upload price-history CSV (optional)", type=["csv"])
    st.caption("Required columns: product_id, product_name, date, price. Optional columns such as category and discount_percent are retained.")

try:
    raw_data = load_csv(uploaded_file) if uploaded_file is not None else load_csv(DATA_FILE)
    data = prepare_data(raw_data)
except FileNotFoundError:
    st.error("Dataset not found. Place price_history.csv inside the data folder, or upload a CSV in the sidebar.")
    st.stop()
except (ValueError, pd.errors.ParserError, UnicodeDecodeError) as exc:
    st.error(f"Could not read the dataset: {exc}")
    st.stop()

is_demo = uploaded_file is None
if is_demo:
    st.info("The bundled dataset is synthetic demo data. Results from it are for demonstrating the workflow.")

product_names = (data[["product_id", "product_name"]].drop_duplicates("product_id")
                 .sort_values("product_name"))
options = product_names["product_id"].tolist()
name_by_id = dict(zip(product_names["product_id"], product_names["product_name"]))

with st.sidebar:
    selected_id = st.selectbox(
        "Choose a product",
        options,
        format_func=lambda pid: f"{name_by_id[pid]} ({pid})",
    )
    forecast_days = st.slider("Forecast horizon (days)", min_value=1, max_value=30, value=7)

product = data[data["product_id"] == selected_id].sort_values("date").copy()
product = product.groupby("date", as_index=False).agg({"product_name": "last", "price": "mean", **({"category": "last"} if "category" in product.columns else {}), **({"discount_percent": "mean"} if "discount_percent" in product.columns else {})})

st.header("Dataset overview")
a, b, c = st.columns(3)
a.metric("Valid observations", f"{len(data):,}")
b.metric("Products", f"{data['product_id'].nunique():,}")
c.metric("Date range", f"{data['date'].min():%d %b %Y} – {data['date'].max():%d %b %Y}")

st.header(name_by_id[selected_id])
if "category" in data.columns:
    categories = data.loc[data["product_id"] == selected_id, "category"].dropna().unique()
    if len(categories):
        st.caption(f"Category: {categories[0]}")

latest_date = product["date"].max()
latest_price = float(product.loc[product["date"] == latest_date, "price"].iloc[-1])

if len(product) < 5:
    st.warning("At least five distinct dated observations are recommended for a basic train/test evaluation. Add more history to enable reliable evaluation and forecasting.")
    st.line_chart(product.set_index("date")["price"].rename("Price (₹)"))
    st.metric("Latest recorded price", f"₹{latest_price:,.2f}")
    st.stop()

X, start_date = make_features(product)
y = product["price"].to_numpy(dtype=float)

# Keep the latest 20% of observations as a chronological holdout set.

# Chronological train/test split
split_index = max(3, int(len(product) * 0.8))
if len(product) - split_index < 2:
    split_index = len(product) - 2

X_train, X_test = X[:split_index], X[split_index:]
y_train, y_test = y[:split_index], y[split_index:]

# Future dates
future_dates = pd.date_range(
    latest_date + pd.Timedelta(days=1),
    periods=forecast_days,
    freq="D"
)

future_days = np.array(
    [(d - start_date).days for d in future_dates],
    dtype=float
).reshape(-1, 1)

# Store model results
model_metrics = []
future_forecasts = {}
evaluation_forecasts = {}

# 1. Linear Regression
lr_eval = LinearRegression()
lr_eval.fit(X_train, y_train)
lr_test = np.maximum(lr_eval.predict(X_test), 0)

lr_final = LinearRegression()
lr_final.fit(X, y)
lr_future = np.maximum(lr_final.predict(future_days), 0)

evaluation_forecasts["Linear Regression"] = lr_test
future_forecasts["Linear Regression"] = lr_future

# Time-series models need enough training observations
if len(y_train) >= 6:
    # 2. Holt's Linear Trend
    try:
        holt_eval = ExponentialSmoothing(
            y_train,
            trend="add",
            damped_trend=True,
            initialization_method="estimated"
        ).fit()

        holt_test = np.maximum(
            holt_eval.forecast(len(y_test)), 0
        )

        holt_final = ExponentialSmoothing(
            y,
            trend="add",
            damped_trend=True,
            initialization_method="estimated"
        ).fit()

        holt_future = np.maximum(
            holt_final.forecast(forecast_days), 0
        )

        evaluation_forecasts["Holt's Trend"] = holt_test
        future_forecasts["Holt's Trend"] = np.asarray(holt_future)

    except Exception as exc:
        st.warning(f"Holt's Trend could not be fitted: {exc}")

    # 3. ARIMA
    try:
        arima_eval = ARIMA(
            y_train,
            order=(1, 1, 0)
        ).fit()

        arima_test = np.maximum(
            arima_eval.forecast(steps=len(y_test)), 0
        )

        arima_final = ARIMA(
            y,
            order=(1, 1, 0)
        ).fit()

        arima_future = np.maximum(
            arima_final.forecast(steps=forecast_days), 0
        )

        evaluation_forecasts["ARIMA"] = np.asarray(arima_test)
        future_forecasts["ARIMA"] = np.asarray(arima_future)

    except Exception as exc:
        st.warning(f"ARIMA could not be fitted: {exc}")
else:
    st.info(
        "Holt's Trend and ARIMA need at least 6 training "
        "observations. Collect more price history to compare them."
    )

# Evaluate each model on the same holdout period
for model_name, predictions in evaluation_forecasts.items():
    model_mae = mean_absolute_error(y_test, predictions)
    model_rmse = float(
        np.sqrt(mean_squared_error(y_test, predictions))
    )
    model_r2 = (
        r2_score(y_test, predictions)
        if len(y_test) >= 2 and np.unique(y_test).size > 1
        else None
    )

    model_metrics.append({
        "Model": model_name,
        "MAE (₹)": model_mae,
        "RMSE (₹)": model_rmse,
        "R²": model_r2
    })

# Combine available forecasts using the median
forecast_matrix = np.vstack(list(future_forecasts.values()))
future_prices = np.median(forecast_matrix, axis=0)

next_price = float(future_prices[0])
change_pct = (
    (next_price - latest_price) / latest_price * 100
    if latest_price else 0.0
)

# Model performance table
metrics_df = pd.DataFrame(model_metrics).sort_values("MAE (₹)")
best_model = metrics_df.iloc[0]["Model"]

st.subheader("Price history and forecast")

history = pd.DataFrame({
    "Actual price (₹)": product.set_index("date")["price"]
})

forecast = pd.DataFrame(
    future_forecasts,
    index=future_dates
)
forecast["Median estimate (₹)"] = future_prices

chart_data = history.join(forecast, how="outer")
st.line_chart(chart_data)

st.caption("Forecast is an extrapolated linear trend, not a guaranteed future selling price. The model does not account for sudden discounts, stock changes or sale events.")

m1, m2, m3 = st.columns(3)
m1.metric("Latest recorded price", f"₹{latest_price:,.2f}", help=f"Recorded on {latest_date:%d %b %Y}")
m2.metric("Next-day estimate", f"₹{next_price:,.2f}", f"{change_pct:+.2f}% vs latest")
m3.metric(f"Estimate in {forecast_days} days", f"₹{float(future_prices[-1]):,.2f}")


st.header("Model evaluation")

st.write(
    f"Models trained on the first {len(X_train):,} observations "
    f"and tested on the latest {len(X_test):,} observations "
    "in chronological order."
)

st.dataframe(
    metrics_df.round(3),
    use_container_width=True,
    hide_index=True
)

st.success(
    f"Best holdout performance by MAE: {best_model}"
)

st.caption(
    "Lower MAE and RMSE indicate smaller errors. "
    "The median forecast combines the available models. "
    "The forecast range is not a statistical confidence interval."
)

with st.expander("View selected product data"):
    display_cols = [col for col in ["date", "product_id", "product_name", "category", "price", "discount_percent"] if col in product.columns]
    st.dataframe(product[display_cols].sort_values("date", ascending=False), use_container_width=True, hide_index=True)
    csv_bytes = product.to_csv(index=False).encode("utf-8")
    st.download_button("Download selected product history", csv_bytes, file_name=f"{selected_id}_price_history.csv", mime="text/csv")
