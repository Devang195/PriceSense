"""Rebuild the bundled simulated 3-year price history (not retailer records).

Deterministic seed, changing sale dates and discount depths, distinct product
trends and demand patterns. Does not modify any forecasting outputs or models.
Run from the project folder: python generate_seasonal_history.py
"""
from pathlib import Path
import json
import math
from datetime import date, timedelta
from collections import defaultdict
import numpy as np
from sync_datasets import main as sync_csvs

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'pricesense_api_scraper' / 'data'
START, END = date(2023, 11, 15), date(2026, 11, 14)
SEED = 27182


def select_catalogue(products, limit=50):
    """Keep category diversity and preserve the original product IDs."""
    grouped = defaultdict(list)
    for p in products:
        grouped[p['category']].append(p)
    chosen = []
    while len(chosen) < min(limit, len(products)):
        for group in grouped.values():
            if group and len(chosen) < limit:
                chosen.append(group.pop(0))
    return sorted(chosen, key=lambda p: p['product_id'])


def generate(products):
    rng = np.random.default_rng(SEED)
    dates = [START + timedelta(days=i) for i in range((END-START).days+1)]
    t = np.arange(len(dates), dtype=float)
    weekday = np.array([d.weekday() for d in dates])
    month_phase = np.array([(d.day-1)/((date(d.year+(d.month==12),d.month%12+1,1)-date(d.year,d.month,1)).days) for d in dates])
    annual_phase = 2*np.pi*t/365.25
    windows = json.loads((ROOT/'sale_calendar.json').read_text())['windows']
    # Each year has independently shifted market-wide sale dates. The forecast
    # calendar knows only the recurring approximate window, not these actual dates.
    market_events = []
    for year in range(START.year-1, END.year+1):
        for w in windows:
            month, day = map(int, w['start'].split('-'))
            shift = int(rng.integers(-3,4))
            start = date(year,month,day)+timedelta(days=shift)
            duration = max(3,int(w['days'])+int(rng.integers(-1,3)))
            market_events.append((start,duration,rng.uniform(.8,1.25)))
    records=[]
    for i,p in enumerate(products):
        base=float(p['base_price'])
        # Balanced rising/falling profiles, with a small stable group.
        sign = (1,-1,1,-1,0)[i%5]
        trend = sign*rng.uniform(.00016,.00036) if sign else rng.uniform(-.00004,.00004)
        recent = sign*rng.uniform(.0011,.0023) if sign else rng.uniform(-.0003,.0003)
        recent_days = rng.integers(90,160)
        recent_ramp = np.maximum(t-(len(t)-recent_days),0)
        # Weekly prices vary with day of week; monthly cycle and annual demand
        # create separate, learnable price movements, not random forecast jitter.
        weekly = rng.uniform(.018,.047)*np.cos(2*np.pi*(weekday-2)/7) + rng.uniform(.004,.012)*np.sin(4*np.pi*(weekday-1)/7)
        monthly = rng.uniform(.012,.034)*np.cos(2*np.pi*(month_phase+rng.uniform(-.1,.1)))
        annual = rng.uniform(.015,.06)*np.sin(annual_phase+rng.uniform(0,2*np.pi))
        noise = np.zeros(len(t))
        for j in range(1,len(t)):
            noise[j]=.72*noise[j-1]+rng.normal(0,.004)
        discounts=np.zeros(len(t))
        typical = rng.uniform(.08,.20)
        for start,duration,strength in market_events:
            if rng.random()<.12: continue  # not every item participates
            start += timedelta(days=int(rng.integers(-1,2)))
            duration=max(3,duration+int(rng.integers(-1,2)))
            idx=(start-START).days
            depth=min(.30,typical*strength*rng.uniform(.82,1.18))
            for k in range(duration+5):
                j=idx+k
                if 0<=j<len(t):
                    if k<duration:
                        factor=.75 if k==0 else (0.85 if k==duration-1 else 1.0)
                    else: factor=.55*(1-(k-duration)/5)
                    discounts[j]=max(discounts[j],depth*factor)
        # Infrequent flash deals add unforecastable variability, not exact annual repeats.
        for j in rng.choice(len(t),size=10,replace=False):
            end=min(len(t),j+int(rng.integers(1,4)))
            discounts[j:end]=np.maximum(discounts[j:end],rng.uniform(.025,.075))
        values=base*np.exp(trend*(t-t[-1])+recent*(recent_ramp-recent_ramp[-1])+weekly+monthly+annual+noise)*(1-discounts)
        for d,v in zip(dates,values):
            records.append(dict(product_id=p['product_id'],product_name=p['product_name'],category=p['category'],date=d.isoformat(),price=round(float(v),2),currency=p['currency']))
    return records


def main():
    products=select_catalogue(json.loads((DATA/'products.json').read_text(encoding='utf-8')))
    records=generate(products)
    (DATA/'products.json').write_text(json.dumps(products,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (DATA/'price_history.json').write_text(json.dumps(records,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    sync_csvs()
    (DATA/'DATASET_INFO.txt').write_text(f'Synthetic simulation, not verified retailer history. Product names are catalogue labels, not assertions about availability on historical dates.\n{len(products)} products, {len(set(p["category"] for p in products))} categories, {len(records)} daily records.\nPeriod: {START} through {END} (inclusive).\nSeed: {SEED}. Recreate with generate_seasonal_history.py.\nSale dates, participation, discount depths and recovery vary across years and products.\n',encoding='utf-8')

if __name__=='__main__': main()
