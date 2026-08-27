#!/usr/bin/env python3
"""Exchange a Strava OAuth authorization code for a refresh token.

Usage:
  python scripts/exchange_token.py CLIENT_ID CLIENT_SECRET AUTH_CODE

Send each rider this URL (replace CLIENT_ID):

  https://www.strava.com/oauth/authorize?client_id=CLIENT_ID&response_type=code&redirect_uri=http://localhost&approval_prompt=force&scope=activity:read_all

After they click Authorize, their browser lands on a localhost error page.
That is expected. Have them copy the FULL URL from the address bar and send it
to you right away (codes expire in minutes). The code is the code= parameter.
"""
import json, sys, urllib.request, urllib.parse

def main():
    if len(sys.argv) != 4:
        print(__doc__)
        sys.exit(1)
    cid, csec, code = sys.argv[1], sys.argv[2], sys.argv[3]
    if "code=" in code:  # accept a pasted full redirect URL too
        code = urllib.parse.parse_qs(urllib.parse.urlparse(code).query)["code"][0]
    body = urllib.parse.urlencode({
        "client_id": cid, "client_secret": csec,
        "code": code, "grant_type": "authorization_code",
    }).encode()
    with urllib.request.urlopen("https://www.strava.com/oauth/token", data=body, timeout=30) as r:
        tok = json.loads(r.read().decode())
    ath = tok.get("athlete", {})
    print(f"Athlete: {ath.get('firstname','?')} {ath.get('lastname','?')} (id {ath.get('id','?')})")
    print(f"REFRESH TOKEN: {tok['refresh_token']}")
    print("Store this as the athlete's STRAVA_REFRESH_* secret in GitHub.")

if __name__ == "__main__":
    main()
