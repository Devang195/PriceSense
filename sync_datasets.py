"""Regenerate all bundled demo CSVs from the API's canonical JSON dataset."""

import csv
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
API = ROOT / "pricesense_api_scraper"
COLUMNS = ["product_id", "product_name", "category", "date", "price", "currency"]


def write_csv(path, columns, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def main():
    catalogue = json.loads((API / "data" / "products.json").read_text(encoding="utf-8"))
    records = json.loads((API / "data" / "price_history.json").read_text(encoding="utf-8"))
    products = {p["product_id"]: p for p in catalogue}
    grouped = defaultdict(list)
    seen = set()
    for row in records:
        key = (row["product_id"], row["date"])
        product = products[row["product_id"]]
        if key in seen or row["price"] <= 0:
            raise ValueError(f"Invalid or duplicate observation: {key}")
        if any(row[k] != product[k] for k in ("product_name", "category", "currency")):
            raise ValueError(f"Catalogue mismatch: {key}")
        seen.add(key)
        grouped[row["product_id"]].append(row["price"])
    if set(grouped) != set(products):
        raise ValueError("The catalogue and history contain different product IDs.")

    rows = [{k: row[k] for k in COLUMNS} for row in sorted(records, key=lambda r: (r["product_id"], r["date"]))]
    write_csv(ROOT / "data" / "price_history.csv", COLUMNS, rows)
    print(f"Synchronized {len(rows):,} prices for {len(products):,} products.")


if __name__ == "__main__":
    main()
