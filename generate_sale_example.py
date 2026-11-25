"""Create a reproducible, explicitly synthetic two-year sale-pattern CSV example."""
from pathlib import Path
import numpy as np
import pandas as pd
from simulation_calendar import calendar_features


def main():
    dates = pd.date_range('2024-11-15', '2026-11-14', freq='D')
    rng = np.random.default_rng(42)
    sale, recovery, _ = calendar_features(dates)
    t = np.arange(len(dates))
    log_prices = (np.log(30000) - 0.00012*t + .012*np.sin(2*np.pi*t/7)
                  + .009*np.cos(2*np.pi*(np.asarray(dates.day)-1)/np.asarray(dates.days_in_month))
                  - .14*sale - .045*recovery + rng.normal(0,.004,len(t)))
    data = pd.DataFrame({'product_id':'SALE_EXAMPLE', 'product_name':'Synthetic sale-pattern example',
                         'category':'Example', 'date':dates.strftime('%Y-%m-%d'),
                         'price':np.round(np.exp(log_prices),2), 'currency':'INR'})
    path = Path(__file__).with_name('data') / 'sale_pattern_example.csv'
    data.to_csv(path,index=False)
    print(f'Wrote {len(data)} synthetic observations to {path}')

if __name__ == '__main__':
    main()
