"""KOS OpenAPI の統計クエリ（読み取り専用）で、カウンセラー販売実績ダッシュボードの元データを月ごとに取得する。

    python3 -I pipeline/sales/counselor/fetch.py WORK FROM TO [--only purchase,schedule,...]

FROM / TO は JST の日付（両端を含む）。例: 2026-03-20 2026-10-10
WORK/raw/<データ>_<YYYY-MM>.json に1か月ずつ保存する（API の期間は1回1か月以内、limit 200 でページング）。
JST の日 D は UTC (D-1)T15:00Z .. DT15:00Z。

取得するデータ（いずれも患者データを含む。リポジトリの外に置くこと）:
    purchase  購入項目統計         ≒ 購入エクスポート（会計金額・担当・商品カテゴリ・返金状態・流入チャネル）
    schedule  予約統計             ≒ 予約来院エクスポート（カウンセリング進行ステップ滞在時間・カウンセラー名）
    prepaid   プリペイドカード履歴 ≒ プリペイドカードエクスポート
    survey    満足度調査の回答      （pipeline/kos_client.py と同じ取得方法）
    procedure 施術タスク統計（照合用。ダッシュボードの数値には使わない）
    transaction 決済統計（照合用）
"""
import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..'))
import kos_client  # noqa: E402

JST = dt.timezone(dt.timedelta(hours=9))
# name -> (path, from-field, to-field)
DATASETS = {
    'purchase': ('/statistics/open/v1/queries/get-purchase-item-statistics', 'createdDateTimeUtcFrom', 'createdDateTimeUtcTo'),
    'schedule': ('/statistics/open/v1/queries/get-schedule-statistics', 'reservationStartDateTimeUtcFrom', 'reservationStartDateTimeUtcTo'),
    'prepaid': ('/statistics/open/v1/queries/get-prepaid-card-charging-event-statistics', 'chargedDateTimeUtcFrom', 'chargedDateTimeUtcTo'),
    'procedure': ('/statistics/open/v1/queries/get-procedure-task-statistics', 'completedDateTimeUtcFrom', 'completedDateTimeUtcTo'),
    'transaction': ('/statistics/open/v1/queries/get-transaction-statistics', 'createdTimeUtcFrom', 'createdTimeUtcTo'),
}
DEFAULT = ['purchase', 'schedule', 'prepaid', 'survey']


def utc(day):
    """JST の DAY 0:00 を API の UTC 文字列に。"""
    return (dt.datetime.combine(day, dt.time(), JST) - dt.timedelta(hours=9)).strftime('%Y-%m-%dT%H:%M:%SZ')


def months(d0, d1):
    """[d0, d1]（両端含む）を月ごとの (YYYY-MM, 開始日, 終了日の翌日) に分ける。"""
    out, m = [], d0.replace(day=1)
    while m <= d1:
        nm = (m.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        out.append((m.strftime('%Y-%m'), max(m, d0), min(nm, d1 + dt.timedelta(days=1))))
        m = nm
    return out


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
            except (urllib.error.URLError, ConnectionError, TimeoutError):
                if attempt == 3:
                    raise
                time.sleep(3 + 5 * attempt)
        raise RuntimeError(f'{path}: failed after retries')

    def query(self, name, start_utc, end_utc, limit=200):
        path, f, t = DATASETS[name]
        data, cursor, total = [], None, None
        while True:
            body = {'limit': limit, f: start_utc, t: end_utc}
            if cursor:
                body['cursor'] = cursor
            res = self.post(path, body)
            data += res.get('data', [])
            total = res.get('totalCount', total)
            cursor = res.get('nextCursor')
            if not cursor:
                return {'totalCount': total, 'from': start_utc, 'to': end_utc, 'data': data}


def raw_path(work, name, ym):
    return os.path.join(work, 'raw', f'{name}_{ym}.json')


def _survey(start_utc, end_utc):
    for attempt in range(4):
        try:
            return kos_client.fetch_survey_answers(start_utc, end_utc)
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            if attempt == 3:
                raise
            time.sleep(3 + 5 * attempt)


def fetch(work, d0, d1, names=DEFAULT, quiet=False, skip_existing=False):
    os.umask(0o077)
    os.makedirs(os.path.join(work, 'raw'), exist_ok=True)
    os.chmod(work, 0o700)
    cl = Client()
    for ym, a, b in months(d0, d1):
        for name in names:
            out = raw_path(work, name, ym)
            if skip_existing and os.path.exists(out):
                continue
            if name == 'survey':
                res = _survey(utc(a), utc(b))
                res.update({'from': utc(a), 'to': utc(b)})
            else:
                res = cl.query(name, utc(a), utc(b))
            with open(out, 'w') as fh:
                json.dump(res, fh, ensure_ascii=False)
            if not quiet:
                print(f'{name:11s} {ym} {a}..{b - dt.timedelta(days=1)}: {len(res["data"])} rows (totalCount {res["totalCount"]})', flush=True)


def load(work, name, yms):
    """取得済みの月ファイルを結合（同じ行が2回入らないよう ID で重複除去）。"""
    key = {'purchase': None, 'schedule': 'scheduleId', 'prepaid': 'chargingId', 'survey': 'id',
           'procedure': 'procedureTaskId', 'transaction': None}[name]
    rows, seen = [], set()
    for ym in yms:
        p = raw_path(work, name, ym)
        if not os.path.exists(p):
            continue
        for r in json.load(open(p))['data']:
            if key:
                if r.get(key) in seen:
                    continue
                seen.add(r.get(key))
            rows.append(r)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('work')
    ap.add_argument('date_from')
    ap.add_argument('date_to')
    ap.add_argument('--only', default=','.join(DEFAULT), help='comma separated: ' + ','.join(list(DATASETS) + ['survey']))
    ap.add_argument('--skip-existing', action='store_true', help='既に保存済みの月ファイルは取り直さない（中断後の再開用）')
    a = ap.parse_args()
    fetch(a.work, dt.date.fromisoformat(a.date_from), dt.date.fromisoformat(a.date_to), a.only.split(','),
          skip_existing=a.skip_existing)


if __name__ == '__main__':
    main()
