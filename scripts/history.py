#!/usr/bin/env python3
"""Rebuild data/history.js: the season, day by day, for the jersey race charts.

Extracted from .github/workflows/history.yml so the weekly digest can call the
same code before it renders the chart images for the email. Two copies would
drift, and the drift would be invisible: the chart in the email and the chart
on the site would quietly disagree about the same race.

Reads the Strava refresh tokens from the environment, same names the workflows
already use. Writes data/history.js and prints a cross check against the season
totals in state.json.
"""
import datetime, json, os, sys, time, urllib.parse, urllib.request

YEAR = 2026
COUNTED = ("Ride", "VirtualRide", "GravelRide", "MountainBikeRide")
M, FT = 1609.344, 3.280839895

def post(url, data):
    r = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode(),
                               method="POST")
    with urllib.request.urlopen(r) as f:
        return json.load(f)

def get(url, token):
    for attempt in range(4):
        try:
            r = urllib.request.Request(
                url, headers={"Authorization": f"Bearer {token}"})
            with urllib.request.urlopen(r) as f:
                return json.load(f), f.headers.get("X-RateLimit-Usage")
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 3:
                print("  429, waiting 60s")
                time.sleep(60)
                continue
            raise
    raise RuntimeError("gave up")

state = json.load(open("data/state.json"))

# Pacific, not the runner. The season and every ride bucket by local day.
try:
    from zoneinfo import ZoneInfo
    today = datetime.datetime.now(ZoneInfo("America/Los_Angeles")).date()
except Exception:
    today = (datetime.datetime.now(datetime.timezone.utc)
             - datetime.timedelta(hours=8)).date()
if today.year != YEAR:
    today = datetime.date(YEAR, 12, 31)

start = datetime.date(YEAR, 1, 1)
days = [(start + datetime.timedelta(days=i)).isoformat()
        for i in range((today - start).days + 1)]
idx = {d: i for i, d in enumerate(days)}

miles, feet, names = {}, {}, []
usage = None
reads = 0
for key, ath in sorted(state["athletes"].items()):
    name = ath["display"]
    rt = os.environ.get("RT_" + key.upper())
    if not rt:
        print(f"[{name}] no token, skipped")
        continue
    names.append(name)
    tok = post("https://www.strava.com/oauth/token", {
        "client_id": os.environ["CID"], "client_secret": os.environ["CSEC"],
        "grant_type": "refresh_token", "refresh_token": rt})["access_token"]

    after = int(datetime.datetime(YEAR, 1, 1,
                                  tzinfo=datetime.timezone.utc).timestamp()) - 86400
    acts, page = [], 1
    while page <= 8:
        batch, usage = get(
            "https://www.strava.com/api/v3/athlete/activities"
            f"?after={after}&per_page=200&page={page}", tok)
        reads += 1
        if not batch:
            break
        acts += batch
        page += 1

    y = (ath.get("season") or {}).get(str(YEAR)) or {}
    counted = {int(x) for x in (y.get("ids") or [])}

    dm = [0.0] * len(days)
    df = [0.0] * len(days)
    n = 0
    seen = set()
    for a in acts:
        aid = int(a.get("id") or 0)
        if aid not in counted or aid in seen:
            continue
        d = (a.get("start_date_local") or "")[:10]
        if d not in idx:
            continue
        seen.add(aid)
        dm[idx[d]] += float(a.get("distance") or 0) / M
        df[idx[d]] += float(a.get("total_elevation_gain") or 0) * FT
        n += 1
    missing = len(counted) - len(seen)
    if missing:
        print(f"[{name}] WARNING {missing} counted activities were not "
              f"returned by the summary pages")

    cm, cf, rm, rf = [], [], 0.0, 0.0
    for i in range(len(days)):
        rm += dm[i]
        rf += df[i]
        cm.append(round(rm, 1))
        cf.append(round(rf))
    miles[name] = cm
    feet[name] = cf
    print(f"[{name}] {n:4d} rides  ->  {cm[-1]:,.1f} mi, {cf[-1]:,.0f} ft")

out = {"year": str(YEAR), "updated": today.isoformat(),
       "riders": names, "days": days, "miles": miles, "feet": feet}
with open("data/history.js", "w") as f:
    f.write("window.HISTORY=" + json.dumps(out, separators=(",", ":")) + ";\n")
if os.path.exists("data/history.json"):
    os.remove("data/history.json")     # one source of truth, not two
sz = os.path.getsize("data/history.js")
print(f"\nwrote data/history.js  {len(days)} days, {len(names)} riders, {sz:,} bytes")
print(f"reads used: {reads}   rate limit usage: {usage}")

# cross check against the totals the rest of the site uses
print("\ncheck against state.json season totals:")
for key, ath in sorted(state["athletes"].items()):
    nm = ath["display"]
    if nm not in miles:
        continue
    y = (ath.get("season") or {}).get(str(YEAR)) or {}
    want_m = float(y.get("dist_m") or 0) / M
    want_f = float(y.get("elev_m") or 0) * FT
    dmi = miles[nm][-1] - want_m
    dfe = feet[nm][-1] - want_f
    # anything but a rounding difference means the two disagree
    flag = "" if (abs(dmi) < 1.0 and abs(dfe) < 30) else "   <-- CHECK"
    print(f"  {nm:7s} miles {miles[nm][-1]:9,.1f} vs {want_m:9,.1f} "
          f"({dmi:+7.1f})   feet {feet[nm][-1]:9,.0f} vs {want_f:9,.0f} "
          f"({dfe:+7.0f}){flag}")
