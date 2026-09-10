"""Run one independent collector with a deadline and persist hard failures."""
import argparse
import datetime as dt
import json
from pathlib import Path
import subprocess
import os
import signal
import sys
from safe_save import mark_failed, _load_existing

JOBS = {'futures':'futures', 'nikkei225':'nikkei225', 'japan_stocks':'japan_stocks',
        'pts_ranking':'pts_ranking', 'volume_stocks':'volume_stocks',
        'market_news':'market_news', 'earnings_flash':'earnings_flash', 'themes':'themes'}

def run(name, timeout=120):
    start = dt.datetime.now(dt.timezone.utc)
    path = f'data/{JOBS[name]}.json'
    logdir = Path('logs'); logdir.mkdir(exist_ok=True)
    logpath = logdir / f'{name}.log'
    code, reason = 0, None
    try:
        with logpath.open('w') as log:
            process = subprocess.Popen([sys.executable, f'scripts/fetch_{name}.py'],
                                       stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                code = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                raise
        if code:
            reason = f'collector_exit={code}; logs/{name}.log を参照'
    except subprocess.TimeoutExpired:
        code, reason = 124, f'collector_timeout: {timeout}秒; logs/{name}.log を参照'
    except Exception as exc:
        code, reason = 1, f'{type(exc).__name__}: {exc}'
    if reason:
        mark_failed(path, reason, start.isoformat(), {'log':str(logpath), 'exit_code':code})
    data = _load_existing(path) or {}
    if data.get('fetch_status') == 'stale':
        code = code or 1
    text = logpath.read_text() if logpath.exists() else ''
    print(text[-16000:])
    print(json.dumps({'event':'collector_finished', 'dataset':name, 'exit_code':code,
                      'elapsed_seconds':round((dt.datetime.now(dt.timezone.utc)-start).total_seconds(), 1),
                      'status':data.get('fetch_status'), 'log':str(logpath)}))
    return code

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('name', choices=JOBS)
    parser.add_argument('--timeout', type=int, default=120)
    args = parser.parse_args()
    raise SystemExit(run(args.name, args.timeout))
