"""Japan cash/PTS sessions. All session dates are Asia/Tokyo, not UTC.
JPX holidays: https://www.jpx.co.jp/corporate/about-jpx/calendar/
PTS: https://www.japannext.co.jp/ja/pts (17:00–next 06:00).
"""
import datetime as dt
import jpholiday
JST = dt.timezone(dt.timedelta(hours=9))

def business_day(day):
    return day.weekday() < 5 and not jpholiday.is_holiday(day) and (day.month, day.day) not in {(1, 1), (1, 2), (1, 3), (12, 31)}

def previous_day(day):
    day -= dt.timedelta(days=1)
    while not business_day(day):
        day -= dt.timedelta(days=1)
    return day

def next_day(day):
    day += dt.timedelta(days=1)
    while not business_day(day):
        day += dt.timedelta(days=1)
    return day

def at(day, hour, minute=0):
    return dt.datetime.combine(day, dt.time(hour, minute), JST)

def market_context(market='tse', now=None):
    now = (now or dt.datetime.now(JST)).astimezone(JST)
    day, minute = now.date(), now.hour * 60 + now.minute
    if market == 'pts':
        if minute < 360 and business_day(day - dt.timedelta(days=1)):
            session, state = day - dt.timedelta(days=1), 'open'
        elif minute >= 1020 and business_day(day):
            session, state = day, 'open'
        else:
            session, state = previous_day(day), 'closed'
        # At 06:00 the just-ended session is still yesterday's session.
        if state == 'open':
            boundary = at(session + dt.timedelta(days=1), 6)
        else:
            opening = day if business_day(day) and minute < 1020 else next_day(day)
            boundary = at(opening, 17)
    else:
        session = day if business_day(day) and minute >= 540 else previous_day(day)
        state = ('holiday' if not business_day(day) else 'preopen' if minute < 540 else
                 'open' if minute < 690 or 750 <= minute < 930 else
                 'lunch' if minute < 750 else 'closed')
        boundary = (at(day, 9) if state == 'preopen' else at(day, 12, 30) if state == 'lunch'
                    else at(day, 11, 30) if state == 'open' and minute < 690
                    else at(day, 15, 30) if state == 'open' else at(next_day(day), 9))
    return {'session_date': session.isoformat(), 'state': state,
            'label': {'open':'取引時間中', 'closed':'取引時間外', 'holiday':'休場日',
                      'preopen':'寄り付き前', 'lunch':'昼休み'}[state],
            'next_transition_at': boundary.isoformat()}

def parse_time(value):
    if not value:
        return None
    try:
        value = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
        return value.replace(tzinfo=JST) if value.tzinfo is None else value
    except (ValueError, TypeError, AttributeError):
        return None

def session_valid_until(session_date, market, fetched_at, as_of=None, now=None):
    now = now or dt.datetime.now(JST)
    context = market_context(market, now)
    day = dt.date.fromisoformat(session_date)
    if session_date != context['session_date']:
        return at(day, 0).isoformat()
    fetched = parse_time(fetched_at) or at(day, 0)
    if context['state'] == 'open':
        stamp = parse_time(as_of) or fetched
        return min(fetched + dt.timedelta(minutes=60), stamp + dt.timedelta(minutes=60)).isoformat()
    # A pre-close snapshot must not be kept current for the whole weekend.
    close = at(day + dt.timedelta(days=1), 6) if market == 'pts' else at(day, 15, 30)
    if context['state'] == 'lunch':
        close = at(day, 11, 30)
    stamp = parse_time(as_of) or fetched
    if stamp < close - dt.timedelta(minutes=20):
        return (stamp + dt.timedelta(minutes=60)).isoformat()
    return (parse_time(context['next_transition_at']) + dt.timedelta(minutes=30)).isoformat()
