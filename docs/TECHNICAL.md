# PriceSense — An ML-Based Price Predictor

**Version 2.3: learned recurring discounts, event-aware ensemble and interactive charts.**

PriceSense is an academic forecasting prototype. It analyzes dated product prices and predicts 1–30 days ahead using Holt's Trend, seasonal Holt-Winters, ARIMA, Gradient Boosting and the custom PriceSense Adaptive Forecaster (PAF). Their forecasts are combined by inverse-squared-MAE weighting calibrated on earlier chronological folds. The naive last-price prediction remains a benchmark/fallback.

**Important:** The bundled 50-product / 54,800-observation dataset is *synthetic* and is not live retailer price history. Predicted values are not shopping guarantees.

## Start on Windows (recommended)

1. Install Python **3.11 or later**.
2. Extract the ZIP, open a terminal **inside the `PriceSense` folder**.
3. Install packages once:
   ```bat
   python -m pip install -r requirements.txt
   ```
4. Double-click **`run_pricesense.bat`**. Or run:
   ```bat
   python -m uvicorn pricesense_api_scraper.api:app --host 127.0.0.1 --port 8000
   ```
5. Open **http://127.0.0.1:8000/**. API documentation: **http://127.0.0.1:8000/docs**.

No `npm`, Node.js, React build, Streamlit server, cloud account or chart CDN is needed. Once Python dependencies are installed, the web interface and dataset can run offline.

## Structure

| File / folder | Purpose |
| --- | --- |
| `frontend/index.html` | Page layout, controls and navigation |
| `frontend/styles.css` | Responsive styling (dark dashboard) |
| `frontend/app.js` | Browser behavior, SVG charts, download and API requests |
| `forecast_engine.py` | Statistical/ML forecasting and holdout evaluation, independent of UI |
| `adaptive_forecaster.py` | Custom NumPy seasonal/event-aware forecasting model |
| `sale_calendar.json` | Synthetic dataset generator assumptions only (not used in forecasting) |
| `simulation_calendar.py` | Calendar helper used only by the synthetic example generator |
| `generate_seasonal_history.py` | Rebuilds the bundled three-year synthetic dataset, with reproducible random seed and varied sale timing |
| `generate_sale_example.py` | Recreates the separate two-year synthetic scenario CSV |
| `pricesense_api_scraper/api.py` | FastAPI server for both website and API |
| `pricesense_api_scraper/data/` | Canonical synthetic product history + catalogue (JSON) |
| `data/price_history.csv` | Synchronized CSV for offline analysis (not required by the API) |
| `sync_datasets.py` | Rebuilds the offline CSV from canonical JSON |
| `run_pricesense.bat` | Starts the single backend/frontend server |

The legacy `app.py` Streamlit dashboard has been **removed**, as have `streamlit`, `altair`, `matplotlib` and unused UI dependencies.

## What happens on the website?

1. The browser loads HTML/CSS/JavaScript from FastAPI.
2. JavaScript requests `/api/catalog` for category/product choices and overview counts.
3. On product selection, it requests `/api/forecast?product_id=P001&horizon=7`.
4. FastAPI prepares the daily series, fits/evaluates the models through `forecast_engine.py`, and returns JSON.
5. JavaScript displays dynamic SVG graphs, price cards, a model-comparison table, weights and sortable/date-filtered data views. The chart axis can zoom into real price changes; **no forecast prices are modified for presentation**.

For an uploaded CSV, the browser sends the file to `/api/upload/preview` and then `/api/forecast-upload`; it is **not stored permanently by the server**. CSVs must be 10 MB or smaller and contain at least `product_id,product_name,date,price`. Optional `category` and `discount_percent` fields are accepted. Missing dates are filled forward after selecting a product.

## API endpoints

- `GET /health` — health status
- `GET /products` — bundled catalogue
- `GET /prices?product_id=P001` — bundled history, optionally filtered
- `GET /prices/P001` — history for a product
- `GET /api/catalog` — UI product catalogue and dataset counts
- `GET /api/forecast?product_id=P001&horizon=7` — full forecast and evaluation in JSON
- `POST /api/upload/preview` — uploaded CSV product list and counts (multipart `file` field)
- `POST /api/forecast-upload?product_id=X&horizon=7` — forecast CSV product (multipart `file` field)
- `GET /docs` — Swagger UI API reference

## Methodology and interpretation

- All models work with natural-log-transformed prices and are converted back to rupees.
- Three earlier rolling origins calibrate weights. For the bundled 1,096-day series, the final **14 days** are a separate untouched test period. The original ARIMA candidates and Gradient Boosting hyperparameters are unchanged.
- Weight formula: `raw_i = 1 / (calibration_MAE_i² + 1e-9)`; divide each raw weight by the sum to normalize it. The naive last-price model is a reference, not a usual member of the ensemble.
- MAE, RMSE, MAPE and R² are reported on the held-out period.
- The shaded uncertainty band is an **approximation** from holdout RMSE, not a statistically calibrated interval.
- A flat prediction is a legitimate model result and should not be artificially made wavy. PriceSense shows a forecast close-up for smaller movements.

## Deploy (one server)

For Render or another Python-friendly host, connect this project and use:

```bash
pip install -r requirements.txt
```

Start command:

```bash
uvicorn pricesense_api_scraper.api:app --host 0.0.0.0 --port $PORT
```

Set the working/root directory to `PriceSense` if your repository contains that wrapper folder. No separate Streamlit Cloud deployment is needed. The historical dataset and frontend are served together on the same origin.

## Editing the frontend without learning React

- **HTML** (`frontend/index.html`) controls what appears on the page.
- **CSS** (`frontend/styles.css`) controls colors, spacing and responsive layout.
- **JavaScript** (`frontend/app.js`) listens to user actions, requests predictions from FastAPI and draws the SVG graphs.
- **Python** (`forecast_engine.py`) is where the actual forecasting algorithms live. You can develop models without touching the frontend code.

## Animated loading screen

- On startup, PriceSense displays a full-screen SVG/CSS animation of rising and falling lines while the catalogue and first forecast load.
- When selecting another product or generating another forecast, the same animation shows during calculation.
- The lines on this loading screen are **illustrative**, not actual or live price forecasts. Actual chart values are calculated by the Python forecasting engine.
- The animation is built into `frontend/index.html` and `frontend/styles.css`, with visibility controlled by `frontend/app.js`. It requires no extra libraries.
- The loader respects the operating system's reduced-motion preference.

## Interface copy

The main dashboard uses concise catalogue labels. Data provenance remains visible in the Product data tab and in API responses. The animated startup graph is decorative.

## Custom PriceSense Adaptive Forecaster (PAF)

PAF is a custom NumPy log-price regression with trend, weekly and monthly Fourier features. It uses recency-weighted ridge regression, three robust reweighting passes and a damped future trend. Minimum training length: 56 days.

### Learning recurring discounts from prices

1. Estimate regular price with a rolling 35-day median, removing typical weekday effects. Calculate log-price residuals.
2. Detect multi-day negative residuals exceeding the larger of 0.045 log units or 2.5 robust standard deviations; merge one-day gaps and extend episodes into observed recovery. Only completed episodes qualify.
3. Cluster starts within approximately ten calendar days of a historical episode, using at most one episode per year. At least two distinct years must support a recurring pattern; isolated flash sales do not establish a recurring window. Fewer than 365 days of training history disables detection.
4. Estimate the future effect from the observed episode shapes, actual year-to-year start offsets, +/- one day of additional timing uncertainty and observed recurrence frequency. This yields an expected log-discount profile, not a guaranteed sale date or depth. The UI lists observed start dates and the estimated window and peak effect.
5. Remove the learned historical discount component from the advanced models' training series. Each predicts the regular price, then receives the same learned future discount exactly once. Naive repeats the raw last price. The five adjusted model forecasts are combined with the existing inverse-squared-MAE weights. Thus low PAF weight no longer cancels the explicit event component.

Regular log-price model: `b = intercept + trend + weekly + monthly + recent_residual`. Weighted ridge solution: `beta = solve(X.T @ W @ X + Lambda, X.T @ W @ y)`. If `e(h) <= 0` is the learned expected log-discount, each advanced forecast is `exp(b_i(h) + e(h))` (bounded for numerical safety), and the ensemble is `sum(w_i * forecast_i(h))`. The event effect is therefore shared, not applied twice. The expected discount relative to the regular forecast is `100 * (1 - exp(e(h)))`.

Every calibration, holdout and deployment origin independently learns events from its own training prefix. No future observations or fixed sale calendar are used at inference. The detector can miss a sale or confuse repeated demand dips with discounts; it does not know retailer intentions. Three years of simulated history do not establish real-world accuracy. The separate `sale_pattern_example.csv` remains an optional demonstration. `sale_calendar.json` is used only to generate synthetic records, not to predict events. See `validation/event_detection.csv`, `validation/historical_event_checks.csv` and `validation/historical_ensemble_checks.csv` for reproducible simulated-data diagnostics. Run `python validation/check_events.py` and `python validation/check_ensemble_events.py` to reproduce them. On the retrospective November 2025 period, the PAF discount adjustment improved 13 of the 26 products for which it inferred windows, and the sample full ensemble improved 2 of 3 products compared with its regular-price blend. These are diagnostic results, not guarantees of improvement.

The prior project report describes the earlier four-model/Streamlit implementation. If submitting this version, update the report's architecture, technology stack, algorithms, screenshots and evaluation results to match the current frontend and fifth advanced model.

## Seasonal catalogue (version 2.2)

- 50 products across 22 categories; 1,096 consecutive observations per product (15 Nov 2023–14 Nov 2026), totalling 54,800 records. Product names are simulation labels, not evidence of historical availability.
- Balanced rising, falling and relatively stable base-price profiles; weekly/monthly cycles, category-independent varying demand, random flash sales and recovery. Each recurring sale has a varied start date, duration, participation and discount depth.
- Recurring discounts are inferred from the history rather than from the synthetic generator calendar. Forecast weights are calibrated on event-adjusted predictions; independent holdout methodology remains unchanged.
- The forecast defaults to 30 days; the uncertainty band can be enabled when needed. Connection-status badges are removed from the interface, but API error messages and the API itself remain.
- Run `python generate_seasonal_history.py` to rebuild all bundled JSON and CSV datasets. The separate sale-pattern upload example can be regenerated with `python generate_sale_example.py`.
- The new histories are simulations, not real historical prices. They do not establish real-world predictive accuracy.

## Interactive charts

Enable **Compare individual models** to display the six available individual forecasts, including the gray dotted naive benchmark. Each model has a fixed color and line style; click its legend entry to show or hide it in both charts. Hover over a forecast date to see all visible model prices.

Both charts have independent zoom and pan controls. Use + / − to zoom, arrows to pan, or Reset to restore the selected history window or forecast horizon. On desktop, Ctrl (or Command on Mac) + mouse wheel zooms around the pointer, and dragging pans a zoomed chart. The price axis automatically scales to visible prices, without changing forecast values. Estimated future sale windows are shaded in both charts when visible.
