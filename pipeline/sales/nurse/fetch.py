"""KOS OpenAPI（読み取り専用）から看護師ダッシュボードの元データを月ごとに取得する。

    python3 -I pipeline/sales/nurse/fetch.py WORK FROM TO

FROM / TO は JST の日付（両端を含む）。WORK/raw/<データ>_<YYYY-MM>.json に1か月ずつ保存する。
取得・ページング・再試行はカウンセラー版（pipeline/sales/counselor/fetch.py）をそのまま使う。

    procedure  施術タスク統計（完了日時で検索）  ≒ 施術エクスポート
    purchase   購入項目統計（作成日時で検索）    ≒ 購入エクスポート
    survey     満足度調査の回答（提出日時で検索） ≒ 満足度調査アンケート結果

いずれも患者データを含む。リポジトリの外（例 /tmp/sales-work/nurse、chmod 700）に置くこと。
"""
import argparse
import datetime as dt
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location('counselor_fetch', os.path.join(HERE, '..', 'counselor', 'fetch.py'))
_c = importlib.util.module_from_spec(_spec)   # pipeline/sales/counselor/fetch.py（同名なので別名で読む）
_path = list(sys.path)
_spec.loader.exec_module(_c)
sys.path[:] = _path   # counselor/fetch.py adds pipeline/ to the front; keep this folder's modules first

NAMES = ['procedure', 'purchase', 'survey']
months, raw_path = _c.months, _c.raw_path


def fetch(work, d0, d1, names=NAMES, quiet=False, skip_existing=False):
    _c.fetch(work, d0, d1, names, quiet=quiet, skip_existing=skip_existing)


def load(work, name, d0, d1):
    """d0..d1 を含む月のファイルを結合（施術タスク・満足度調査は ID で重複除去）。"""
    return _c.load(work, name, [m for m, _, _ in months(d0, d1)])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('work')
    ap.add_argument('date_from')
    ap.add_argument('date_to')
    ap.add_argument('--only', default=','.join(NAMES))
    ap.add_argument('--skip-existing', action='store_true')
    a = ap.parse_args()
    fetch(a.work, dt.date.fromisoformat(a.date_from), dt.date.fromisoformat(a.date_to), a.only.split(','),
          skip_existing=a.skip_existing)


if __name__ == '__main__':
    main()
