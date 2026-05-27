"""Fetch one iWine from current cursor range and dump what we actually get."""
import os, sys, time
from pathlib import Path

for line in Path('../.env').read_text().splitlines():
    line = line.strip()
    if line and not line.startswith('#') and '=' in line:
        k, v = line.split('=', 1)
        if k.strip() not in os.environ:
            os.environ[k.strip()] = v.strip()

sys.path.insert(0, str(Path(__file__).parent))
from curl_cffi import requests as curl_requests
from selectolax.parser import HTMLParser
import json

BASE = 'https://www.cellartracker.com'
LOGIN_URL = f'{BASE}/password.asp'
username = os.environ['ACHILLES_AUTH_CELLARTRACKER_USERNAME']
password = os.environ['ACHILLES_AUTH_CELLARTRACKER_PASSWORD']

# Load cached cookies if available
cookie_cache = Path('data/ct_cookies.json')
cookies_dict = {}
if cookie_cache.exists():
    try:
        data = json.loads(cookie_cache.read_text())
        if time.time() - data.get('created_at', 0) < 22*3600:
            cookies_dict = {c['name']: c['value'] for c in data['cookies']}
            print(f'Using cached cookies ({len(cookies_dict)} cookies)')
    except:
        pass

if not cookies_dict:
    print('No cached cookies — logging in via curl_cffi...')
    s = curl_requests.Session(impersonate='chrome124')
    s.get(BASE + '/')
    s.post(LOGIN_URL, data={'szUser': username, 'szPassword': password, 'UseCookie': 'true'},
           headers={'Referer': LOGIN_URL, 'Content-Type': 'application/x-www-form-urlencoded'})
    r = s.get(f'{BASE}/default.asp')
    cookies_dict = dict(s.cookies)
    print(f'Logged in, {len(cookies_dict)} cookies')

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Referer': f'{BASE}/default.asp',
}

s2 = curl_requests.Session(impersonate='chrome124')

for iwine in [7491, 7500, 200, 300, 1000]:
    r = s2.get(f'{BASE}/wine.asp?iWine={iwine}', headers=HEADERS, cookies=cookies_dict)
    html = r.text or ''
    lo = html.lower()
    is_challenge = 'human verification' in lo or ('kpsdk' in lo and len(html) < 5000)
    is_blocked   = 'cloudfront' in lo and '403 error' in lo
    is_not_found = 'wine not found' in lo or 'no such wine' in lo or 'this wine has been deleted' in lo
    has_producer = 'producer' in lo
    print(f'iWine={iwine:6d} | HTTP={r.status_code} len={len(html):6d} challenge={is_challenge} blocked={is_blocked} not_found={is_not_found} has_producer={has_producer}')
    if not is_challenge and not is_blocked and not is_not_found and len(html) > 1000:
        # Show title + first 600 chars of body text
        tree = HTMLParser(html)
        title = tree.css_first('title')
        print(f'  title: {title.text() if title else "(none)"}')
        body_text = tree.body.text(separator=' ')[:400] if tree.body else ''
        print(f'  body:  {body_text[:300]}')
        print()
