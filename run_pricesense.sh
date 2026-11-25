#!/bin/sh
cd "$(dirname "$0")" || exit 1
python -m uvicorn pricesense_api_scraper.api:app --host 127.0.0.1 --port 8000
