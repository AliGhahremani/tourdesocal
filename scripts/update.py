#!/usr/bin/env python3
"""Daily updater for tourdesocal.com.

For each athlete with a refresh token, pulls activities since their last check,
scans segment_efforts for the tracked segments, and updates that year's PRs,
attempt counts, power bests and season mileage in data/state.json, then
regenerates data.js for the site.

Everything is scoped to the competition year. A time, an attempt, a power best or
a mile ridden in 2025 counts for 2025 and never leaks into 2026.
"""
import json, os, sys, time, datetime, urllib.request, urllib.parse, urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_PATH = os.path.join(ROOT, "data", "state.json")
META_PATH = os.path.join(ROOT, "data", "meta.json")
DATA_JS_PATH = os.path.join(ROOT, "data.js")
HONOURS_PATH = os.path.join(ROOT, "data", "honours.json")
LAST_RUN_PATH = os.path.join(ROOT, "data", "last_run.json")

API = "https://www.strava.com/api/v3"
_meta = json.load(open(META_PATH))
TRACKED = {s["id"] for s in _meta["segments"]}
OVERLAP = 3 * 86400  # re-scan 3 days back to catch late uploads
PWINDOWS = [300, 600, 1200, 1800, 3600]  # power best-effort windows (sec)

# Rate limits, per https://developers.strava.com/docs/rate-limits/
#   - limits are per APPLICATION, so all four riders share one pool
#   - 15 minute windows align to :00, :15, :30, :45 past the hour
#   - the daily allowance resets at midnight UTC
#   - requests that violate the short term limit STILL COUNT toward the daily
#     total, so blind retrying is actively expensive
# Strava reports usage on every response via X-ReadRateLimit-Usage / -Limit, each
# "fifteen_minute,daily". We read those instead of guessing, which is the whole
# reason this is not just a hardcoded counter.
# Headroom left on the daily counter. It is deliberately larger than one run
# needs, because 2024michael shares this allowance and runs at 08:00. A backfill
# chewing through every last read would starve the other site.
DAILY_RESERVE = 200
# Sleeps through a 15 minute window boundary allowed in ONE run, however the need
# is discovered: pre-emptively, or by eating a 429. Kept low because the backfill
# is driven by a workflow that fires every 15 minutes and commits each time, so a
# run that stops early loses nothing and a long run risks losing everything to a
# job timeout.
MAX_WINDOW_WAITS = 1
MAX_RETRIES = 4             # attempts for a single request, not a time budget
_rl = {"reads": 0, "waits": 0, "win_used": None, "win_limit": None,
       "day_used": None, "day_limit": None}

class BudgetExhausted(Exception):
    """Out of rate limit for now. Save progress and resume on the next run."""

def _note_limits(headers):
    """Record Strava's own usage figures from the response headers."""
    usage = headers.get("X-ReadRateLimit-Usage") or headers.get("X-RateLimit-Usage")
    limit = headers.get("X-ReadRateLimit-Limit") or headers.get("X-RateLimit-Limit")
    if not usage or not limit:
        return
    try:
        wu, du = [int(x) for x in usage.split(",")[:2]]
        wl, dl = [int(x) for x in limit.split(",")[:2]]
    except ValueError:
        return
    _rl.update(win_used=wu, win_limit=wl, day_used=du, day_limit=dl)

def _seconds_to_next_window():
    """Windows align to :00, :15, :30, :45. Add slack so we land inside the next one."""
    return 15 * 60 - (int(time.time()) % (15 * 60)) + 15

def http(url, data=None, token=None):
    is_read = data is None
    for attempt in range(MAX_RETRIES + 1):
        # If Strava has told us the daily allowance is effectively gone, stop now.
        # Waiting cannot help: the daily counter only resets at midnight UTC.
        if is_read and _rl["day_limit"] is not None:
            if _rl["day_limit"] - _rl["day_used"] <= DAILY_RESERVE:
                raise BudgetExhausted(
                    f"daily read limit nearly spent ({_rl['day_used']}/{_rl['day_limit']}); "
                    f"resets at midnight UTC")
        # If the 15 minute window is nearly spent, wait for it rather than
        # spending requests on 429s, which still count against the daily total.
        if is_read and _rl["win_limit"] is not None and attempt == 0:
            if _rl["win_limit"] - _rl["win_used"] <= 2 and _rl["waits"] < MAX_WINDOW_WAITS:
                _rl["waits"] += 1
                w = _seconds_to_next_window()
                print(f"15 min window nearly spent ({_rl['win_used']}/{_rl['win_limit']}). "
                      f"waiting {w}s [daily {_rl['day_used']}/{_rl['day_limit']}]", flush=True)
                time.sleep(w)

        req = urllib.request.Request(url, data=data)
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                _note_limits(r.headers)
                if is_read:
                    _rl["reads"] += 1
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            _note_limits(e.headers)
            if e.code != 429:
                raise
            # A 429 that is really the daily cap cannot be waited out.
            if _rl["day_limit"] is not None and _rl["day_used"] >= _rl["day_limit"]:
                raise BudgetExhausted(
                    f"daily read limit reached ({_rl['day_used']}/{_rl['day_limit']}); "
                    f"resets at midnight UTC")
            if _rl["waits"] >= MAX_WINDOW_WAITS or attempt >= MAX_RETRIES:
                raise BudgetExhausted("out of window waits for this run")
            _rl["waits"] += 1
            w = _seconds_to_next_window()
            print(f"429. waiting {w}s for the window "
                  f"[window {_rl['win_used']}/{_rl['win_limit']}, "
                  f"daily {_rl['day_used']}/{_rl['day_limit']}, "
                  f"{_rl['reads']} reads this run]", flush=True)
            time.sleep(w)
    raise BudgetExhausted("unreachable")

def refresh_access_token(client_id, client_secret, refresh_token):
    body = urllib.parse.urlencode({
        "client_id": client_id, "client_secret": client_secret,
        "grant_type": "refresh_token", "refresh_token": refresh_token,
    }).encode()
    return http("https://www.strava.com/oauth/token", data=body)

def fmt_time(sec):
    m, s = divmod(int(sec), 60)
    if m >= 60:
        h, m = divmod(m, 60)
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"

def fmt_date(iso):
    d = datetime.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return d.strftime("%b %-d, %Y") if os.name != "nt" else d.strftime("%b %d, %Y").replace(" 0", " ")

def best_window_avgs(times, watts, windows):
    """Best average watts for each window, from time/watts streams."""
    if not times or not watts or len(times) != len(watts):
        return {}
    dur = int(times[-1])
    if dur <= 0:
        return {}
    series = [0] * (dur + 1)
    last, ptr = 0, 0
    for t in range(dur + 1):
        while ptr < len(times) and times[ptr] <= t:
            if watts[ptr] is not None:
                last = watts[ptr]
            ptr += 1
        series[t] = last
    prefix = [0]
    for v in series:
        prefix.append(prefix[-1] + v)
    n = len(series)
    out = {}
    for w in windows:
        if n < w:
            continue
        best = max(prefix[i + w] - prefix[i] for i in range(n - w + 1))
        if best > 0:
            out[w] = round(best / w)
    return out

def main():
    cid = os.environ["STRAVA_CLIENT_ID"]
    csec = os.environ["STRAVA_CLIENT_SECRET"]
    tokens = {
        "ali": os.environ.get("STRAVA_REFRESH_ALI", ""),
        "jake": os.environ.get("STRAVA_REFRESH_JAKE", ""),
        "randee": os.environ.get("STRAVA_REFRESH_RANDEE", ""),
        "michael": os.environ.get("STRAVA_REFRESH_MICHAEL", ""),
        "abe": os.environ.get("STRAVA_REFRESH_ABE", ""),
        "jose": os.environ.get("STRAVA_REFRESH_JOSE", ""),
    }

    # The backfill fires every 15 minutes. Once the daily allowance is gone,
    # every firing would otherwise spend one read per rider learning that again,
    # which is about 500 wasted reads over the rest of a day. The flag carries the
    # UTC date it was set, so it clears itself when Strava's counter resets.
    today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    try:
        prev = json.load(open(LAST_RUN_PATH))
    except Exception:
        prev = {}
    if prev.get("daily_spent_on") == today:
        print(f"daily read allowance already spent today "
              f"({prev.get('rate_limit_daily')}). resets at midnight UTC. "
              f"nothing to do.", flush=True)
        print("::notice::Daily Strava read allowance already spent; skipped.")
        return

    connected = [k for k, v in tokens.items() if v]
    state = json.load(open(STATE_PATH))
    changed = False
    summary = []
    # GitHub Actions logs need a sign in, so anything an unattended check needs to
    # know gets written to data/last_run.json and committed. That file is public.
    report = {"riders": {}, "notes": []}

    for key, ath in state["athletes"].items():
        rt = tokens.get(key)
        if not rt:
            print(f"[{key}] no refresh token configured - skipping")
            continue
        try:
            tok = refresh_access_token(cid, csec, rt)
        except Exception as e:
            print(f"[{key}] token refresh FAILED: {e}", file=sys.stderr)
            continue
        access = tok["access_token"]
        since = max(0, int(ath.get("last_epoch", 0)) - OVERLAP)
        now = int(time.time())
        # Defined before the try, not inside it. The budget can run out on the
        # very first call of a rider's pass, and the handler below reads this. If
        # it only existed further down, that raise turned into an
        # UnboundLocalError and killed the whole run without saving anything.
        progress_epoch = None
        try:

            # ---- Strava athlete id, fetched once and cached ----
            # Used to link each rider's name on the site to their Strava profile.
            if not ath.get("strava_id"):
                try:
                    me = http(f"{API}/athlete", token=access)
                    if me.get("id"):
                        ath["strava_id"] = int(me["id"])
                        changed = True
                        print(f"[{key}] strava id {ath['strava_id']}")
                except BudgetExhausted:
                    raise
                except Exception as e:
                    print(f"[{key}] could not read athlete id: {e}", file=sys.stderr)

            # list activities since last check (paginated)
            acts, page = [], 1
            while True:
                batch = http(f"{API}/athlete/activities?after={since}&per_page=100&page={page}", token=access)
                acts.extend(batch)
                if len(batch) < 100:
                    break
                page += 1
            print(f"[{key}] {len(acts)} activities since {since}")
            report["riders"].setdefault(key, {})["activities_seen"] = len(acts)
            # Oldest first. If we run out of budget partway, last_epoch can advance to
            # the last activity we actually finished and tomorrow picks up from there.
            acts.sort(key=lambda a: a.get("start_date") or "")

            for a in acts:
                if a.get("type") not in ("Ride", "VirtualRide", "GravelRide", "MountainBikeRide"):
                    continue
                try:
                    detail = http(f"{API}/activities/{a['id']}?include_all_efforts=true", token=access)
                except BudgetExhausted:
                    # Out of budget is not "this activity is broken, skip it". If
                    # the handler below swallows it, every remaining activity is
                    # skipped the same way, each one spending a real 429 that still
                    # counts against the daily total, and then last_epoch is
                    # stamped as though the whole year had been read. That is how a
                    # rider ends up marked complete holding only January, with
                    # their faster rides later in the year never looked at.
                    raise
                except Exception as e:
                    print(f"[{key}] activity {a['id']} fetch failed: {e}", file=sys.stderr)
                    continue

                # ---- global exclusions: no e-bikes, no Peloton, for segments AND power ----
                # Ali's rule: e-bike and Peloton rides do not count for anything.
                # Zwift and other smart trainer rides arrive as VirtualRide with
                # device_watts and are deliberately allowed.
                dev = str(detail.get("device_name") or "").lower()
                if detail.get("type") == "EBikeRide" or "peloton" in dev:
                    print(f"[{key}] skipping {a['id']}: e-bike or Peloton")
                    time.sleep(1)
                    continue
                # Everything is scoped to the competition year: a 2026 time only
                # counts for 2026, and so do the attempts behind it. Strava's
                # athlete_segment_stats.effort_count is all-time with no date
                # breakdown, so it cannot be used here. We count efforts as we
                # scan them instead, which is also 14 fewer API calls per rider.
                act_year = (a.get("start_date_local") or a.get("start_date") or "")[:4]
                if act_year.isdigit():
                    yrec = ath.setdefault("season", {}).setdefault(
                        act_year, {"dist_m": 0.0, "elev_m": 0.0, "rides": 0, "ids": [],
                                   "bests": {}, "attempts": {}})
                    yrec.setdefault("bests", {})
                    yrec.setdefault("attempts", {})
                    counted = yrec.setdefault("eff_ids", [])
                    if not isinstance(yrec.get("_effseen"), set):
                        yrec["_effseen"] = set(counted)

                    for eff in detail.get("segment_efforts", []):
                        sid = eff.get("segment", {}).get("id")
                        if sid not in TRACKED:
                            continue
                        sid_s = str(sid)
                        sec = int(eff["elapsed_time"])

                        # Attempts, deduped by effort id so a rescan cannot inflate them.
                        eid = eff.get("id")
                        if eid is not None and eid not in yrec["_effseen"]:
                            yrec["_effseen"].add(eid)
                            counted.append(eid)
                            yrec["attempts"][sid_s] = yrec["attempts"].get(sid_s, 0) + 1
                            changed = True

                        best = yrec["bests"].get(sid_s)
                        if best is None or sec < best["sec"]:
                            watts = eff.get("average_watts")
                            yrec["bests"][sid_s] = {
                                "sec": sec, "time": fmt_time(sec),
                                "date": fmt_date(eff.get("start_date_local", a.get("start_date_local", ""))),
                                "watts": round(watts) if watts else None,
                            }
                            changed = True
                            summary.append(
                                f"{ath['display']} new {act_year} best on segment {sid}: {fmt_time(sec)}")

                # ---- power bests: real meters only (e-bike/Peloton already excluded above) ----
                try:
                    dev = str(detail.get("device_name") or "").lower()
                    if (detail.get("device_watts") and detail.get("type") != "EBikeRide"
                            and "peloton" not in dev):
                        sj = http(f"{API}/activities/{a['id']}/streams?keys=time,watts&key_by_type=true", token=access)
                        tt = (sj.get("time") or {}).get("data") or []
                        ww = (sj.get("watts") or {}).get("data") or []
                        bests = best_window_avgs(tt, ww, PWINDOWS)
                        # Year scoped on purpose. Everything else on this site is
                        # scoped to the competition year, so a power best set in a
                        # previous season does not stand in the current one.
                        if act_year.isdigit():
                            pw = yrec.setdefault("power", {})
                            for w, val in bests.items():
                                k = str(w)
                                if val > int(pw.get(k) or 0):
                                    pw[k] = val
                                    changed = True
                                    summary.append(
                                        f"{ath['display']} new {act_year} {w//60} min power: {val} W")
                except BudgetExhausted:
                    raise          # same reason as the activity fetch above
                except Exception as e:
                    print(f"[{key}] power calc failed for {a['id']}: {e}", file=sys.stderr)
                # Season totals. Idempotent: every counted activity id is recorded,
                # so the 3 day rescan overlap cannot double count. Strava's
                # /athletes/{id}/stats would give ytd totals in one call, but it
                # cannot exclude e-bikes, and e-bikes count for nothing here.
                try:
                    yr = (a.get("start_date_local") or a.get("start_date") or "")[:4]
                    if yr.isdigit():
                        season = ath.setdefault("season", {}).setdefault(
                            yr, {"dist_m": 0.0, "elev_m": 0.0, "rides": 0, "ids": []})
                        if not isinstance(season.get("_seen"), set):
                            season["_seen"] = set(season.get("ids") or [])
                        aid = int(a["id"])
                        if aid not in season["_seen"]:
                            season["_seen"].add(aid)
                            season["ids"].append(aid)
                            season["dist_m"] += float(a.get("distance") or 0)
                            season["elev_m"] += float(a.get("total_elevation_gain") or 0)
                            season["rides"] += 1
                            # Time on the bike, split indoor vs outdoor. Zwift and
                            # other trainers arrive as VirtualRide. They count for
                            # everything, but the weekly digest likes to know who
                            # has been riding a screen all week.
                            mt = int(a.get("moving_time") or 0)
                            season["time_s"] = int(season.get("time_s") or 0) + mt
                            if a.get("type") == "VirtualRide" or a.get("trainer"):
                                season["vtime_s"] = int(season.get("vtime_s") or 0) + mt
                                season["vrides"] = int(season.get("vrides") or 0) + 1
                            changed = True
                except Exception as e:
                    print(f"[{key}] season totals failed for {a.get('id')}: {e}",
                          file=sys.stderr)

                progress_epoch = int(datetime.datetime.fromisoformat(
                    (a.get("start_date") or "").replace("Z", "+00:00")).timestamp()) \
                    if a.get("start_date") else progress_epoch
                time.sleep(1)  # be polite to rate limits

            if ath.get("last_epoch") != now:
                ath["last_epoch"] = now
                changed = True
        except BudgetExhausted as e:
            # Not a failure. We used our share of the rate limit. Save how far we
            # got so tomorrow resumes instead of starting over, and keep going
            # with the other riders (they will hit the same wall and save too).
            print(f"[{key}] stopped early: {e}", file=sys.stderr)
            print(f"::notice::{key} stopped early (not a failure): {e}")
            report["riders"].setdefault(key, {})["stopped_early"] = str(e)
            if progress_epoch and progress_epoch > int(ath.get("last_epoch", 0)):
                ath["last_epoch"] = progress_epoch
                changed = True
                print(f"[{key}] progress saved. resumes from {progress_epoch}", file=sys.stderr)

    if changed:
        state["updated"] = datetime.date.today().strftime("%b %d, %Y").replace(" 0", " ")
    # _seen is an in-memory set for dedupe; the persisted list is "ids".
    for _a in state["athletes"].values():
        for _y in (_a.get("season") or {}).values():
            _y.pop("_seen", None)
            _y.pop("_effseen", None)
    json.dump(state, open(STATE_PATH, "w"), indent=2)

    # regenerate data.js regardless (cheap, idempotent)
    # Everything on the site is scoped to this competition year.
    year = datetime.date.today().strftime("%Y")
    meta = json.load(open(META_PATH))
    segs_out = []
    for seg in meta["segments"]:
        sid_s = str(seg["id"])
        riders = []
        for key, ath in state["athletes"].items():
            yrec = (ath.get("season") or {}).get(year) or {}
            b = (yrec.get("bests") or {}).get(sid_s)
            att = (yrec.get("attempts") or {}).get(sid_s)
            if b:
                riders.append({"name": ath["display"], "sec": b["sec"], "time": b["time"],
                               "date": b["date"], "watts": b["watts"], "attempts": att})
            else:
                riders.append({"name": ath["display"], "sec": None, "time": "—",
                               "date": "never attempted", "watts": None, "attempts": att})
        riders.sort(key=lambda r: (r["sec"] is None, r["sec"] if r["sec"] is not None else 0))
        seg_out = dict(seg)
        seg_out["riders"] = riders
        seg_out["pl"] = meta["polylines"][sid_s]
        # Grades are optional. A segment without them draws in one flat colour
        # rather than not drawing at all, so meta.json can be added to a segment
        # at a time without breaking the map.
        gr = (meta.get("grades") or {}).get(sid_s)
        if gr and len(gr) == len(seg_out["pl"]):
            seg_out["gr"] = gr
        segs_out.append(seg_out)

    power_out = {}
    for key, ath in state["athletes"].items():
        yp = ((ath.get("season") or {}).get(year) or {}).get("power") or {}
        yp = {k: v for k, v in yp.items() if v}
        if yp:
            power_out[ath["display"]] = yp
    links_out = {}
    for key, ath in state["athletes"].items():
        if ath.get("strava_id"):
            links_out[ath["display"]] = f"https://www.strava.com/athletes/{ath['strava_id']}"
    # Season classifications: total distance and elevation for the calendar year,
    # bikes only, e-bikes and Peloton already excluded upstream.
    season_out = []
    for key, ath in state["athletes"].items():
        y = (ath.get("season") or {}).get(year)
        if not y:
            continue
        season_out.append({
            "name": ath["display"],
            "miles": round(y["dist_m"] / 1609.344, 1),
            "feet": round(y["elev_m"] * 3.280839895),
            "rides": y["rides"],
        })
    # ---- General Classification, computed here as well as in the browser ----
    # The site scores GC client side, but the archive needs the finishing order
    # in Python. Same rule: total elapsed time, a missed segment costs the
    # slowest finisher's time plus 10 percent.
    PENALTY = 1.10
    gc_totals = {}
    for seg in segs_out:
        fin = [r for r in seg["riders"] if r["sec"] is not None]
        if not fin:
            continue
        pen = round(max(r["sec"] for r in fin) * PENALTY)
        for r in seg["riders"]:
            gc_totals[r["name"]] = gc_totals.get(r["name"], 0) + (
                r["sec"] if r["sec"] is not None else pen)
    gc_out = [{"name": n, "sec": t, "total": fmt_time(t)}
              for n, t in sorted(gc_totals.items(), key=lambda kv: kv[1])]

    # ---- roll of honour ----
    # The first run of a new year freezes the season that just ended: the GC
    # standings as they finished, plus the polka dot and green leaders. Runs once
    # per year because the year is recorded in the file.
    honours = {"seasons": []}
    try:
        if os.path.exists(HONOURS_PATH):
            honours = json.load(open(HONOURS_PATH))
        honours.setdefault("seasons", [])
        done = {h.get("year") for h in honours["seasons"]}
        prev = str(int(year) - 1)
        prev_totals = {}
        for key, ath in state["athletes"].items():
            y = (ath.get("season") or {}).get(prev)
            if y:
                prev_totals[ath["display"]] = y
        if prev not in done and prev_totals:
            gc = [{"name": r["name"], "total": r["total"]} for r in gc_out]
            top = lambda k: max(prev_totals.items(), key=lambda kv: kv[1][k])
            climb = top("elev_m"); miles = top("dist_m")
            honours["seasons"].insert(0, {
                "year": prev,
                "yellow": (gc[0] if gc else None),
                "polka": {"name": climb[0],
                          "feet": round(climb[1]["elev_m"] * 3.280839895)},
                "green": {"name": miles[0],
                          "miles": round(miles[1]["dist_m"] / 1609.344, 1)},
                "gc": gc,
            })
            with open(HONOURS_PATH, "w") as f:
                json.dump(honours, f, indent=2)
                f.write("\n")
            print(f"::notice::Archived the {prev} season to data/honours.json")
    except Exception as e:
        print(f"honours archive failed: {e}", file=sys.stderr)

    payload = {"updated": state["updated"], "segs": segs_out,
               "power": power_out, "links": links_out,
               "year": year, "season": season_out,
               "honours": honours.get("seasons", [])}
    with open(DATA_JS_PATH, "w") as f:
        f.write("window.SITE_DATA = ")
        json.dump(payload, f, separators=(",", ":"))
        f.write(";\n")

    rate_line = (f"{_rl['reads']} reads this run, {_rl['waits']} window waits. "
                 f"Strava reports window {_rl['win_used']}/{_rl['win_limit']}, "
                 f"daily {_rl['day_used']}/{_rl['day_limit']}.")
    print("RATE LIMIT:", rate_line)
    print(f"::notice::Rate limit: {rate_line}")
    print("SUMMARY:", "; ".join(summary) if summary else "no PR changes")

    # Public run report. Actions logs need authentication; this file does not, so
    # an unattended check can read it from raw.githubusercontent.com.
    report.update({
        "finished_utc": datetime.datetime.now(datetime.timezone.utc)
                          .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "reads_this_run": _rl["reads"],
        "window_waits": _rl["waits"],
        "rate_limit_window": f"{_rl['win_used']}/{_rl['win_limit']}",
        "rate_limit_daily": f"{_rl['day_used']}/{_rl['day_limit']}",
        "tokens_present": sorted(k for k, v in tokens.items() if v),
        "tokens_missing": sorted(k for k, v in tokens.items() if not v),
        "changes": summary,
        # Complete is a fact about the data, not about whether THIS run did any
        # work: every connected rider is caught up to roughly now. Defining it as
        # "nobody stopped early" made a run that did nothing at all look finished,
        # which is how the 15 minute backfill would have switched itself off with
        # the job half done.
        "backfill_complete": bool(connected) and all(
            int((state["athletes"].get(k) or {}).get("last_epoch") or 0)
            >= int(time.time()) - 6 * 3600
            for k in connected if k in state["athletes"]
        ),
        # Set only when Strava's own counter says the day is spent, so the next
        # firing can skip straight out.
        "daily_spent_on": today if (
            _rl["day_limit"] is not None
            and _rl["day_limit"] - _rl["day_used"] <= DAILY_RESERVE
        ) else None,
    })
    with open(LAST_RUN_PATH, "w") as f:
        json.dump(report, f, indent=2)
        f.write("\n")

if __name__ == "__main__":
    main()
