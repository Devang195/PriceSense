"""Reproducible catalogue and retrospective November 2025 PAF diagnostics.
Run from project root: python validation/check_events.py
These are simulated-data checks, not external validation.
"""
from pathlib import Path
import sys
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from adaptive_forecaster import learn_sales, adaptive_baseline

def main():
    data=pd.read_csv(ROOT/'data/price_history.csv',parse_dates=['date'])
    detection=[]; checks=[]
    for pid, g in data.groupby('product_id'):
        s=g.sort_values('date').set_index('date').price
        p,f,events=learn_sales(np.log(s),s.index,30)
        detection.append(dict(product_id=pid,product_name=g.product_name.iloc[0],windows=len(events),expected_peak_discount_pct=100*(1-np.exp(f.min())),observed_starts='; '.join(','.join(w['observed_dates']) for w in events)))
        train=s.loc[:'2025-11-14']; actual=s.loc['2025-11-15':'2025-12-14'].to_numpy()
        p,f,events=learn_sales(np.log(train),train.index,len(actual))
        regular=np.exp(adaptive_baseline(np.log(train)-p,train.index,len(actual)))
        pred=regular*np.exp(f)
        checks.append(dict(product_id=pid,windows=len(events),regular_mae=np.mean(abs(regular-actual)),event_aware_mae=np.mean(abs(pred-actual)),predicted_discount_pct=100*(1-np.exp(f.min()))))
    d=pd.DataFrame(detection); c=pd.DataFrame(checks)
    d.to_csv(ROOT/'validation/event_detection.csv',index=False);c.to_csv(ROOT/'validation/historical_event_checks.csv',index=False)
    print(f'Catalogue: {len(d)} products; {sum(d.windows>0)} have learned windows in next 30 days')
    q=c[c.windows>0]; print(f'Historical test: {len(q)} products with learned windows; {sum(q.event_aware_mae<q.regular_mae)} improved; mean regular MAE {q.regular_mae.mean():.2f}, adjusted MAE {q.event_aware_mae.mean():.2f}')
if __name__=='__main__': main()
