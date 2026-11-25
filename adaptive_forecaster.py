"""PAF and historical discount detection; no fixed sale calendar at inference.
All inputs must end at the forecast origin. Event dates are estimates, not
confirmed retailer promotions. NumPy and Pandas implement the model.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

MODEL_NAME = "PriceSense Adaptive (PAF)"
MIN_TRAIN = 56


def _phase(d):
    return (pd.Timestamp(2000, d.month, d.day) - pd.Timestamp(2000, 1, 1)).days


def _distance(a, b):
    return (a - b + 183) % 366 - 183


def learn_sales(train, dates, steps):
    """Return historical and expected future log-discount effects and evidence.

    Detect multi-day negative residuals relative to a local regular-price
    estimate, then cluster starts by annual phase. Require repeat evidence in
    distinct years; isolated flash sales are not scheduled into the future.
    """
    y = np.asarray(train, float)
    dates = pd.DatetimeIndex(dates)
    past = np.zeros(len(y)); future = np.zeros(steps)
    if len(y) < 365:
        return past, future, []
    s = pd.Series(y, index=dates)
    rough = s.rolling(35, center=True, min_periods=10).median().to_numpy()
    dow = np.asarray(dates.dayofweek)
    weekly = np.array([np.median((y-rough)[dow==d]) for d in range(7)])
    adjusted = y-weekly[dow]
    # Median normal-price estimate resists short-lived discounts and follows trend.
    base = pd.Series(adjusted).rolling(35, center=True, min_periods=10).median().to_numpy()
    residual = adjusted-base
    scale = max(.008, 1.4826*np.median(np.abs(residual-np.median(residual))))
    threshold = max(.045, 2.5*scale)
    flag = residual < -threshold
    # Bridge a one-day gap, but require at least two genuinely discounted days.
    bridge = flag.copy(); bridge[1:-1] |= flag[:-2] & flag[2:]
    edges = np.flatnonzero(np.diff(np.r_[False, bridge, False]))
    events = []
    for a,b in zip(edges[::2],edges[1::2]):
        if b-a<2 or b-a>18 or flag[a:b].sum()<2: continue
        # Extend to the first/last softer discount/recovery days.
        lo=a; hi=b
        while lo>max(0,a-2) and residual[lo-1]<-threshold*.48: lo-=1
        while hi<min(len(y),b+5) and residual[hi]<-threshold*.40: hi+=1
        if lo<3 or hi>=len(y): continue  # incomplete episodes cannot establish duration
        depth=float(-np.median(residual[a:b]))
        if depth<threshold: continue
        events.append(dict(a=lo,b=hi,core=b-a,depth=depth,phase=_phase(dates[lo]),year=dates[lo].year))
    remaining=events.copy(); groups=[]
    while remaining:
        # Select the largest cluster of nearby starts, one episode per year.
        candidates=[]
        for seed in remaining:
            near=[e for e in remaining if abs(_distance(e['phase'],seed['phase']))<=10]
            per_year={}
            for e in sorted(near,key=lambda e: (abs(_distance(e['phase'],seed['phase'])),-e['depth'])):
                per_year.setdefault(e['year'],e)
            group=list(per_year.values())
            candidates.append(group)
        group=max(candidates,key=lambda g:(len(g),np.median([e['depth'] for e in g])))
        if len(group)<2: break
        groups.append(group)
        remaining=[e for e in remaining if e not in group]
    future_dates=pd.date_range(dates[-1]+pd.Timedelta(days=1),periods=steps,freq='D')
    windows=[]
    for group in groups:
        anchor=group[0]['phase']
        offsets=np.array([_distance(e['phase'],anchor) for e in group])
        center=int(round(float(np.median(offsets))))
        phase=(anchor+center)%366
        ref=pd.Timestamp(2000,1,1)+pd.Timedelta(days=phase)
        # Only complete historical opportunities count toward recurrence rate.
        opportunities=0
        for year in range(dates[0].year-1,dates[-1].year+1):
            nominal=pd.Timestamp(year,ref.month,min(ref.day,28) if ref.month==2 and ref.day==29 else ref.day)
            if nominal-pd.Timedelta(days=12)>=dates[0] and nominal+pd.Timedelta(days=25)<=dates[-1]: opportunities+=1
        recurrence=min(1.,len(group)/max(len(group),opportunities))
        depth=float(np.median([e['depth'] for e in group]))
        # Use observed episode shapes (including observed recovery), rather than
        # a fixed discount profile. Cap noise at the observed depth range.
        shapes=[]
        for e in group:
            shape=np.clip(residual[e['a']:e['b']],-1.5*e['depth'],0)
            past[e['a']:e['b']]=np.minimum(past[e['a']:e['b']],shape)
            shapes.append(shape)
        for year in range(future_dates[0].year-1,future_dates[-1].year+2):
            nominal=pd.Timestamp(year,ref.month,min(ref.day,28) if ref.month==2 and ref.day==29 else ref.day)
            effect=np.zeros(steps)
            starts=[]; ends=[]
            for offset,shape in zip(offsets,shapes):
                # Empirical dates plus a modest +/- one-day uncertainty.
                for jitter in (-1,0,1):
                    start=nominal+pd.Timedelta(days=int(offset-center+jitter))
                    rel=np.asarray((future_dates-start).days)
                    mask=(rel>=0)&(rel<len(shape))
                    effect[mask]+=shape[rel[mask]]/(3*len(shapes))*recurrence
                    starts.append(start);ends.append(start+pd.Timedelta(days=len(shape)-1))
            future=np.minimum(future,effect)
            if np.any(effect<0):
                windows.append({'name':nominal.strftime('%B')+' recurring discount',
                    'start':min(starts).date().isoformat(),'end':max(ends).date().isoformat(),
                    'likely_start':nominal.date().isoformat(),'observed_years':len(group),
                    'observed_dates':[dates[e['a']].date().isoformat() for e in sorted(group,key=lambda e:e['a'])],
                    'typical_discount_pct':float(100*(1-np.exp(-depth))),
                    'expected_peak_discount_pct':float(100*(1-np.exp(effect.min()))),
                    'recurrence_rate':float(recurrence)})
    return past,future,sorted(windows,key=lambda w:w['start'])


def _features(dates, origin, damp=False):
    dates=pd.DatetimeIndex(dates)
    t=np.asarray((dates-origin).days,float)
    if damp: t=np.where(t>0,30*(1-np.exp(-np.maximum(t,0)/30)),t)
    week=2*np.pi*np.asarray(dates.dayofweek)/7
    month=2*np.pi*(np.asarray(dates.day)-1)/np.asarray(dates.days_in_month)
    return np.column_stack([np.ones(len(dates)),t/30,np.sin(week),np.cos(week),np.sin(2*week),np.cos(2*week),np.sin(month),np.cos(month)])


def adaptive_baseline(train, dates, steps):
    """Weighted robust ridge on the regular-price series."""
    train=np.asarray(train,float); dates=pd.DatetimeIndex(dates)
    if len(train)<MIN_TRAIN: raise ValueError(f'PAF needs at least {MIN_TRAIN} training days')
    if len(train)!=len(dates) or not np.isfinite(train).all(): raise ValueError('Invalid PAF training series')
    origin=dates[-1]; X=_features(dates,origin)
    age=np.asarray((origin-dates).days,float); w=np.exp(-age/180)
    center=float(np.average(train,weights=w)); target=train-center
    penalty=np.diag([0,.5,3,3,5,5,5,5]); effective=w.copy()
    for _ in range(3):
        beta=np.linalg.solve(X.T@(effective[:,None]*X)+penalty,X.T@(effective*target))
        residual=target-X@beta
        scale=max(.005,1.4826*float(np.median(np.abs(residual-np.median(residual)))))
        effective=w*np.minimum(1,3*scale/np.maximum(np.abs(residual),1e-12))
    dates_out=pd.date_range(origin+pd.Timedelta(days=1),periods=steps)
    correction=float(np.median(residual[-3:]))*np.exp(-np.arange(1,steps+1)/7)
    return center+_features(dates_out,origin,True)@beta+correction


def adaptive_forecast(train, dates, steps):
    past,future,_=learn_sales(train,dates,steps)
    return adaptive_baseline(np.asarray(train)-past,dates,steps)+future
