"""KOS OpenAPI client: exchange the API key for a token and fetch satisfaction-survey answers.

Usage:
    python3 -I pipeline/kos_client.py START_UTC END_UTC OUT_JSON [--limit 200]

START_UTC / END_UTC are ISO timestamps (end is exclusive), e.g. a JST day
2026-10-11 is 2026-10-10T15:00:00Z .. 2026-10-11T15:00:00Z. The range must not
exceed 3 months; fetching a whole month with limit 1000 has returned HTTP 500,
so fetch one month at a time with --limit 200.

The key is read from the EHR_API_KEY environment variable. OUT_JSON contains
patient data (names, birth dates, chart numbers, comments): write it outside
the repository (e.g. the session scratchpad), never commit it.
"""
import argparse
import json
import os
import urllib.request

BASE = "https://open-api.kos-solution.com"
SURVEY_PATH = "/schedule/open/v1/queries/find-satisfaction-survey-answers"


def _post(path, body, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = token
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def exchange_token():
    return _post("/open/authorization/commands/exchange-token", {"key": os.environ["EHR_API_KEY"]})["token"]


def fetch_survey_answers(start_utc, end_utc, limit=200):
    token = exchange_token()
    data, cursor, total = [], None, None
    while True:
        body = {"limit": limit, "submittedDateTimeRange": {"startDateTimeUtc": start_utc, "endDateTimeUtc": end_utc}}
        if cursor:
            body["cursor"] = cursor
        res = _post(SURVEY_PATH, body, token)
        data += res.get("data", [])
        total = res.get("totalCount", total)
        cursor = res.get("nextCursor")
        if not cursor:
            return {"totalCount": total, "data": data}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("start_utc")
    ap.add_argument("end_utc")
    ap.add_argument("out_json")
    ap.add_argument("--limit", type=int, default=200)
    a = ap.parse_args()
    res = fetch_survey_answers(a.start_utc, a.end_utc, a.limit)
    os.umask(0o077)
    with open(a.out_json, "w") as f:
        json.dump(res, f, ensure_ascii=False)
    print(f"fetched {len(res['data'])} / totalCount {res['totalCount']}")


if __name__ == "__main__":
    main()
