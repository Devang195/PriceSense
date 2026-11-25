"""Retrospective full-ensemble sale-window diagnostic on three sample products.
Run from the project root: python validation/check_ensemble_events.py
Compare the event-aware prediction with the same regular-price blend before
applying its event effect. Dates after the cutoff are used only for scoring.
"""
from pathlib import Path
import sys
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from forecast_engine import run_forecasting

def main():
    data=pd.read_csv(ROOT/'data/price_history.csv',parse_dates=['date']); rows=[]
    for pid in ['P001','P002','P003']:
        s=data[data.product_id==pid].sort_values('date').set_index('date').price
        train=s.loc[:'2025-11-14'];actual=s.loc['2025-11-15':'2025-12-14'].to_numpy()
        r=run_forecasting(train,len(actual))
        rows.append(dict(product_id=pid,window_count=len(r['sale_windows']),regular_mae=np.mean(abs(r['regular_forecast']-actual)),event_aware_mae=np.mean(abs(r['ensemble']-actual)),peak_discount_pct=max(r['sale_effect_pct'])))
        print(rows[-1],flush=True)
    pd.DataFrame(rows).to_csv(ROOT/'validation/historical_ensemble_checks.csv',index=False)
if __name__=='__main__': main()
