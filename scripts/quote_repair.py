"""Fill a missing last daily close only from a dated quote in the same Yahoo response.
Never fill OHLC candles or infer a date from collection time.
"""
import datetime as dt
import math
from market_clock import JST, market_context

def repair_last_close(history, metadata, now=None):
    now = now or dt.datetime.now(JST)
    if history.empty or 'Close' not in history:
        return history
    expected = market_context('tse', now)['session_date']
    # Only replace a missing close in a bar that actually belongs to this session.
    if history.index[-1].strftime('%Y-%m-%d') != expected or not history['Close'].isna().iloc[-1]:
        return history
    price = metadata.get('regularMarketPrice')
    stamp = metadata.get('regularMarketTime')
    if isinstance(stamp, (int,float)):
        stamp = dt.datetime.fromtimestamp(stamp, JST)
    if not isinstance(stamp, dt.datetime) or stamp.tzinfo is None:
        return history
    if stamp.astimezone(JST).date().isoformat() != expected or stamp > now + dt.timedelta(minutes=5):
        return history
    if not isinstance(price,(int,float)) or not math.isfinite(price) or price<=0:
        return history
    history=history.copy()
    history.loc[history.index[-1],'Close']=price
    return history
