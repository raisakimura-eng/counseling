"""Fetch the KOS statistics needed by the 着地予想ダッシュボード (read-only queries only).

Usage:
    python3 -I pipeline/sales/landing/fetch.py --from 2026-07-01 --to 2026-10-11 --work /tmp/sales-work/landing
        [--future-to 2026-10-31] [--kinds schedule,transaction,purchase,procedure,prepaid] [--visitors]

--from / --to are JST dates (both inclusive). Each kind is fetched month by month
(the API is happiest with ranges of one month or less) into
$WORK/raw/<kind>_<YYYY-MM>.json. A month that ended before the last full fetch is
reused from disk unless --refresh is given; the current month is always re-fetched.
--future-to also fetches *reservations* (schedule, by reservation start) up to that
date, for the forecast of today / month end.
--visitors fills $WORK/raw/visitors.json (visitorId -> dateOfBirth) with
/visitor/open/v1/queries/get-visitor for visitors not cached yet (age bands).

Everything written here contains patient data: keep $WORK outside the repository.
"""
import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))  # pipeline/
import kos_client  # noqa: E402

JST = dt.timezone(dt.timedelta(hours=9))
# kind -> (path, from-field, to-field)
KINDS = {
    'schedule': ('/statistics/open/v1/queries/get-schedule-statistics',
                 'reservationStartDateTimeUtcFrom', 'reservationStartDateTimeUtcTo'),
    'transaction': ('/statistics/open/v1/queries/get-transaction-statistics', 'createdTimeUtcFrom', 'createdTimeUtcTo'),
    'purchase': ('/statistics/open/v1/queries/get-purchase-item-statistics',
                 'createdDateTimeUtcFrom', 'createdDateTimeUtcTo'),
    'procedure': ('/statistics/open/v1/queries/get-procedure-task-statistics',
                  'completedDateTimeUtcFrom', 'completedDateTimeUtcTo'),
    'prepaid': ('/statistics/open/v1/queries/get-prepaid-card-charging-event-statistics',
                'chargedDateTimeUtcFrom', 'chargedDateTimeUtcTo'),
}
VISITOR_PATH = '/visitor/open/v1/queries/get-visitor'


def utc(day):
    """JST midnight at the start of DAY as an API timestamp (JST day D = (D-1)T15:00Z .. DT15:00Z)."""
    return (dt.datetime.combine(day, dt.time(), JST).astimezone(dt.timezone.utc)).strftime('%Y-%m-%dT%H:%M:%SZ')


def next_month(d):
    return (d.replace(day=28) + dt.timedelta(days=4)).replace(day=1)


class Client:
    def __init__(self):
        self.token = kos_client.exchange_token()

    def post(self, path, body):
        for attempt in range(4):
            try:
                return kos_client._post(path, body, self.token)
            except urllib.error.HTTPError as e:
                if e.code == 401:
                    self.token = kos_client.exchange_token()
                elif e.code >= 500 and attempt < 3:
                    time.sleep(2 + 3 * attempt)
                else:
                    raise

    def fetch_all(self, path, body, limit=200):
        data, cursor = [], None
        while True:
            b = dict(body, limit=limit)
            if cursor:
                b['cursor'] = cursor
            res = self.post(path, b)
            data += res.get('data') or []
            cursor = res.get('nextCursor')
            if not cursor:
                return data


def fetch_kind(cli, kind, start, end_excl):
    path, f_from, f_to = KINDS[kind]
    return cli.fetch_all(path, {f_from: utc(start), f_to: utc(end_excl)})


def month_ranges(start, end_incl):
    m = start.replace(day=1)
    while m <= end_incl:
        yield m.strftime('%Y-%m'), max(m, start), min(next_month(m), end_incl + dt.timedelta(days=1))
        m = next_month(m)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--from', dest='frm', required=True)
    ap.add_argument('--to', required=True, help='last JST date with actual data to fetch (inclusive)')
    ap.add_argument('--future-to', help='also fetch reservations up to this JST date (inclusive)')
    ap.add_argument('--work', default=os.environ.get('WORK', '/tmp/sales-work/landing'))
    ap.add_argument('--kinds', default=','.join(KINDS))
    ap.add_argument('--refresh', action='store_true', help='re-fetch closed months too')
    ap.add_argument('--visitors', action='store_true')
    a = ap.parse_args()
    os.umask(0o077)
    raw = os.path.join(a.work, 'raw')
    os.makedirs(raw, exist_ok=True)
    os.chmod(a.work, 0o700)
    frm, to = dt.date.fromisoformat(a.frm), dt.date.fromisoformat(a.to)
    today = dt.datetime.now(JST).date()
    cli = Client()
    for kind in a.kinds.split(','):
        end = to
        if kind == 'schedule' and a.future_to:
            end = max(end, dt.date.fromisoformat(a.future_to))
        for ym, s, e in month_ranges(frm, end):
            out = os.path.join(raw, f'{kind}_{ym}.json')
            closed = next_month(dt.date.fromisoformat(ym + '-01')) <= today - dt.timedelta(days=3)
            if closed and os.path.exists(out) and not a.refresh:
                continue
            # always fetch the whole month (from the 1st) so the file is self-contained
            data = fetch_kind(cli, kind, dt.date.fromisoformat(ym + '-01'), e)
            json.dump({'kind': kind, 'from': utc(dt.date.fromisoformat(ym + '-01')), 'to': utc(e),
                       'fetchedAt': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                       'data': data}, open(out, 'w'), ensure_ascii=False)
            print(f'{kind} {ym}: {len(data)} rows', flush=True)
    if a.visitors:
        fetch_visitors(cli, raw)


def fetch_visitors(cli, raw):
    path = os.path.join(raw, 'visitors.json')
    cache = json.load(open(path)) if os.path.exists(path) else {}
    ids = set()
    for f in os.listdir(raw):
        if f.startswith(('schedule_', 'transaction_')):
            ids |= {r.get('visitorId') for r in json.load(open(os.path.join(raw, f)))['data'] if r.get('visitorId')}
    todo = sorted(ids - set(cache))
    for i, vid in enumerate(todo):
        try:
            v = cli.post(VISITOR_PATH, {'id': vid})
            v = v.get('visitor', v)
            cache[vid] = {'dateOfBirth': v.get('dateOfBirth') or v.get('birthDateUtc') or v.get('birthDayUtc')}
        except urllib.error.HTTPError as e:
            cache[vid] = {'dateOfBirth': None, 'error': e.code}
        if i % 100 == 99:
            json.dump(cache, open(path, 'w'))
    json.dump(cache, open(path, 'w'))
    print(f'visitors: {len(todo)} fetched, {len(cache)} cached')


if __name__ == '__main__':
    main()
