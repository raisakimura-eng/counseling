"""Netlify helpers: download the published index.html of a site and deploy a new one.

The dashboards are single-file sites deployed by "file digest" (the same as a
drag-and-drop deploy), so the site, its URL and its password protection stay as they are.
The token is read from NETLIFY_AUTH_TOKEN.
"""
import hashlib
import json
import os
import time
import urllib.error
import urllib.request

API = 'https://api.netlify.com/api/v1'


def _req(method, path, body=None, ctype='application/json', raw=False, tries=1):
    """One Netlify API call. TRIES > 1 retries a refused / failed call (403, 429, 5xx, network) after 20s, 60s, ...
    On failure the error names Netlify's own message (the 0:30 run of 2026-10-15 only saw 'HTTP Error 403')."""
    headers = {'Authorization': 'Bearer ' + os.environ['NETLIFY_AUTH_TOKEN'], 'Content-Type': ctype}
    data = body if isinstance(body, (bytes, type(None))) else json.dumps(body).encode()
    for i in range(tries):
        req = urllib.request.Request(API + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                b = r.read()
            return b if raw else (json.loads(b) if b else None)
        except urllib.error.HTTPError as e:
            detail = e.read()[:300].decode('utf-8', 'replace')
            err = RuntimeError(f'Netlify {method} {path}: HTTP {e.code} {e.reason}: {detail}')
            if e.code not in (403, 429) and e.code < 500:
                raise err from None
        except urllib.error.URLError as e:
            err = RuntimeError(f'Netlify {method} {path}: {e.reason}')
        if i + 1 < tries:
            print(f'{err} -> retrying', flush=True)
            time.sleep(20 * 3 ** i)
    raise err


def download(site, out):
    """Save the published /index.html of SITE (e.g. 'naaclinic-all-voc') to OUT."""
    b = _req('GET', f'/sites/{site}.netlify.app/files/index.html', ctype='application/vnd.bitballoon.v1.raw', raw=True)
    os.umask(0o077)
    open(out, 'wb').write(b)
    return len(b)


def deploy(site, path, title, require_password=True):
    """Publish PATH as /index.html of SITE and wait until it is live. Returns the deploy id.

    require_password=False is only for the sales dashboards naaclinic and naa-nurse, which the owner decided on
    2026-10-12 to keep public. naa-counselor (with the weekly issues per counselor) and the survey dashboards
    always require protection.
    """
    if require_password and not _req('GET', f'/sites/{site}.netlify.app').get('has_password'):
        raise RuntimeError(f'{site}: password protection is OFF; not deploying a page with patient data. Turn it back on in Netlify.')
    body = open(path, 'rb').read()
    sha = hashlib.sha1(body).hexdigest()
    d = _req('POST', f'/sites/{site}.netlify.app/deploys', {'files': {'/index.html': sha}, 'title': title}, tries=3)
    if sha in (d.get('required') or []):
        _req('PUT', f'/deploys/{d["id"]}/files/index.html', body, ctype='application/octet-stream', tries=3)
    for _ in range(60):
        state = _req('GET', f'/deploys/{d["id"]}')['state']
        if state == 'ready':
            break
        if state == 'error':
            raise RuntimeError(f'{site}: deploy {d["id"]} failed')
        time.sleep(3)
    else:
        raise RuntimeError(f'{site}: deploy {d["id"]} did not become ready')
    live = _req('GET', f'/sites/{site}.netlify.app/files')
    live_sha = next(f['sha'] for f in live if f['path'] == '/index.html')
    if live_sha != sha:
        raise RuntimeError(f'{site}: live index.html does not match the uploaded file')
    return d['id']
