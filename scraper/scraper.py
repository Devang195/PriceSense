
from pathlib import Path
from datetime import date
import re
import time

import requests
import pandas as pd
from bs4 import BeautifulSoup


# Paths are based on this script's location
BASE_DIR = Path(__file__).resolve().parent
PRODUCT_FILE = BASE_DIR / "products.txt"
OUTPUT_FILE = BASE_DIR.parent / "data" / "scraped_prices.csv"

COLUMNS = ["product_id", "product_name", "date", "price"]

HEADERS = {
    "User-Agent": "PriceSenseAcademicProject/1.0"
}


def scrape_product(product_id, url):
    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=20
        )
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        name_tag = soup.find("h1")
        price_tag = soup.find("p", class_="price_color")

        if name_tag is None or price_tag is None:
            print("Product details not found:", url)
            return None

        name = name_tag.get_text(strip=True)
        price_text = price_tag.get_text(strip=True)

        price = float(re.sub(r"[^\d.]", "", price_text))

        return {
            "product_id": product_id,
            "product_name": name,
            "date": date.today().isoformat(),
            "price": price
        }

    except (requests.RequestException, ValueError) as exc:
        print(f"Failed to scrape {url}: {exc}")
        return None


def main():
    if not PRODUCT_FILE.exists():
        print(f"Product file not found: {PRODUCT_FILE}")
        return

    with open(PRODUCT_FILE, "r", encoding="utf-8") as file:
        lines = [
            line.strip()
            for line in file
            if line.strip() and not line.strip().startswith("#")
        ]

    rows = []

    for line in lines:
        try:
            product_id, url = line.split(",", 1)
            product_id = product_id.strip()
            url = url.strip()

            if not product_id or not url:
                print("Invalid entry:", line)
                continue

            result = scrape_product(product_id, url)

            if result is not None:
                rows.append(result)

            time.sleep(1)

        except ValueError:
            print("Invalid format in products.txt:", line)

    new_data = pd.DataFrame(rows, columns=COLUMNS)
    today = date.today().isoformat()

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    if OUTPUT_FILE.exists():
        old_data = pd.read_csv(
            OUTPUT_FILE,
            dtype={"product_id": str}
        )

        missing = set(COLUMNS) - set(old_data.columns)
        if missing:
            print("Existing CSV is missing columns:", missing)
            return

        old_data["date"] = old_data["date"].astype(str).str[:10]

        # Skip product/date combinations already collected
        existing_keys = set(
            zip(old_data["product_id"], old_data["date"])
        )

        new_data = new_data[
            ~new_data.apply(
                lambda row: (row["product_id"], row["date"])
                in existing_keys,
                axis=1
            )
        ]

        data = pd.concat(
            [old_data, new_data],
            ignore_index=True
        )

    else:
        data = new_data

    data.drop_duplicates(
        subset=["product_id", "date"],
        keep="first",
        inplace=True
    )

    data.to_csv(OUTPUT_FILE, index=False)

    print(new_data.to_string(index=False))
    print(f"\nAdded {len(new_data)} new observations.")
    print(f"Saved to: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
