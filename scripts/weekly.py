#!/usr/bin/env python3
"""Weekly digest for tourdesocal.com.

Diffs the live data/state.json against last week's snapshot and writes:

  data/weekly_snapshot.json   this week's numbers, for next week to diff against
  data/weekly_latest.json     the computed digest, so the site can render it
  weekly.html                 a readable archive page
  /tmp/weekly_email.html      the email body, read by the workflow

Reads nothing from Strava, so it costs nothing against the shared rate limit.
It runs after the daily update, on whatever state that update left behind.

The first run has no snapshot to compare against, so it writes a baseline and
says so rather than inventing a week of progress.
"""
import json, os, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(ROOT, "data", "state.json")
META = os.path.join(ROOT, "data", "meta.json")
SNAP = os.path.join(ROOT, "data", "weekly_snapshot.json")
OUT_JSON = os.path.join(ROOT, "data", "weekly_latest.json")
OUT_HTML = os.path.join(ROOT, "weekly.html")
EMAIL_HTML = "/tmp/weekly_email.html"

PENALTY = 1.10
M_PER_MI = 1609.344
FT_PER_M = 3.280839895


def fmt_clock(sec):
    sec = int(round(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def ordinal(n):
    if 10 <= n % 100 <= 20:
        suf = "th"
    else:
        suf = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


def build_current(state, meta, year):
    """Everything the digest needs, in one flat shape, for this year only."""
    seg_name = {str(s["id"]): s["name"] for s in meta["segments"]}
    seg_ids = [str(s["id"]) for s in meta["segments"]]

    riders = {}
    for key, ath in state["athletes"].items():
        y = (ath.get("season") or {}).get(year) or {}
        riders[ath["display"]] = {
            "bests": {k: v["sec"] for k, v in (y.get("bests") or {}).items() if v},
            "times": {k: v["time"] for k, v in (y.get("bests") or {}).items() if v},
            "attempts": dict(y.get("attempts") or {}),
            "power": dict(y.get("power") or {}),
            "dist_m": float(y.get("dist_m") or 0),
            "elev_m": float(y.get("elev_m") or 0),
            "rides": int(y.get("rides") or 0),
        }

    # GC: total elapsed time, a missed segment costs last place plus 10 percent.
    totals = {n: 0 for n in riders}
    ridden = {n: 0 for n in riders}
    for sid in seg_ids:
        got = [r["bests"][sid] for r in riders.values() if sid in r["bests"]]
        if not got:
            continue
        pen = round(max(got) * PENALTY)
        for n, r in riders.items():
            if sid in r["bests"]:
                totals[n] += r["bests"][sid]
                ridden[n] += 1
            else:
                totals[n] += pen

    order = sorted(totals.items(), key=lambda kv: kv[1])
    gc = {n: {"sec": t, "pos": i + 1, "ridden": ridden[n]}
          for i, (n, t) in enumerate(order)}

    started = any(r["bests"] for r in riders.values())
    climb = sorted(riders.items(), key=lambda kv: -kv[1]["elev_m"])
    miles = sorted(riders.items(), key=lambda kv: -kv[1]["dist_m"])
    jerseys = {
        "yellow": order[0][0] if (order and started) else None,
        "polka": climb[0][0] if (climb and climb[0][1]["elev_m"] > 0) else None,
        "green": miles[0][0] if (miles and miles[0][1]["dist_m"] > 0) else None,
    }
    return {"year": year, "riders": riders, "gc": gc, "jerseys": jerseys,
            "seg_name": seg_name, "seg_ids": seg_ids}


def diff(cur, prev):
    """What changed since last week. prev may be None on the first run."""
    d = {"baseline": prev is None, "movers": [], "week": [], "prs": [],
         "tried": [], "power": [], "jerseys": []}
    names = sorted(cur["riders"], key=lambda n: cur["gc"][n]["pos"])

    if prev is None:
        for n in names:
            r = cur["riders"][n]
            d["week"].append({"name": n, "miles": r["dist_m"] / M_PER_MI,
                              "feet": r["elev_m"] * FT_PER_M, "rides": r["rides"]})
        return d

    pr_r = prev.get("riders", {})
    pr_gc = prev.get("gc", {})

    for n in names:
        r = cur["riders"][n]
        p = pr_r.get(n, {})

        # position movement
        was = (pr_gc.get(n) or {}).get("pos")
        now = cur["gc"][n]["pos"]
        if was and was != now:
            d["movers"].append({"name": n, "from": was, "to": now,
                                "up": now < was})

        # distance and climbing added
        dm = r["dist_m"] - float(p.get("dist_m") or 0)
        de = r["elev_m"] - float(p.get("elev_m") or 0)
        dr = r["rides"] - int(p.get("rides") or 0)
        d["week"].append({"name": n, "miles": dm / M_PER_MI,
                          "feet": de * FT_PER_M, "rides": dr})

        # segment PRs and fruitless attempts
        pb, pa = p.get("bests") or {}, p.get("attempts") or {}
        for sid in cur["seg_ids"]:
            new_att = r["attempts"].get(sid, 0) - pa.get(sid, 0)
            if new_att <= 0:
                continue
            old = pb.get(sid)
            new = r["bests"].get(sid)
            seg = cur["seg_name"].get(sid, sid)
            if new is not None and (old is None or new < old):
                d["prs"].append({"name": n, "seg": seg,
                                 "time": r["times"].get(sid, fmt_clock(new)),
                                 "was": fmt_clock(old) if old else None,
                                 "gain": (old - new) if old else None,
                                 "first": old is None, "tries": new_att})
            else:
                d["tried"].append({"name": n, "seg": seg, "tries": new_att,
                                   "best": r["times"].get(sid)})

        # power bests
        pp = p.get("power") or {}
        LBL = {"300": "5 min", "600": "10 min", "1200": "20 min",
               "1800": "30 min", "3600": "1 hr"}
        for k, v in sorted(r["power"].items(), key=lambda kv: int(kv[0])):
            if v > int(pp.get(k) or 0):
                d["power"].append({"name": n, "window": LBL.get(k, k + "s"),
                                   "watts": v, "was": pp.get(k)})

    for j in ("yellow", "polka", "green"):
        a, b = (prev.get("jerseys") or {}).get(j), cur["jerseys"][j]
        if b and a != b:
            d["jerseys"].append({"jersey": j, "to": b, "from": a})
    return d


def render(cur, d, week_end):
    """One HTML body used for both the email and the archive page."""
    C = {"yellow": "#d9a400", "polka": "#c8102e", "green": "#0a7d3c"}
    JN = {"yellow": "Yellow", "polka": "Polka Dot", "green": "Green"}
    UNIT = {"yellow": "GC", "polka": "elevation", "green": "miles"}
    p = []
    A = p.append

    A('<div style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;'
      'max-width:640px;margin:0 auto;color:#16161d;line-height:1.5">')
    A(f'<h1 style="font-size:22px;margin:0 0 2px">Tour de SoCal</h1>')
    A(f'<div style="color:#6d6d78;font-size:13px;margin-bottom:22px">'
      f'Week ending {week_end}</div>')

    if d["baseline"]:
        A('<p style="background:#fff6e5;border:1px solid #f0d9a8;padding:12px 14px;'
          'border-radius:8px;font-size:14px">First digest, so there is nothing to '
          'compare against yet. These are the season totals so far. Next week '
          'reports the change.</p>')

    # jerseys
    A('<h2 style="font-size:15px;margin:22px 0 8px">Jerseys</h2><table '
      'style="border-collapse:collapse;font-size:14px;width:100%">')
    for j in ("yellow", "polka", "green"):
        holder = cur["jerseys"][j] or "nobody yet"
        chg = next((x for x in d["jerseys"] if x["jersey"] == j), None)
        note = (f' <span style="color:#c8102e">new, was {chg["from"]}</span>'
                if chg and chg["from"] else "")
        A(f'<tr><td style="padding:4px 0"><b style="color:{C[j]}">{JN[j]}</b>'
          f'<span style="color:#6d6d78"> ({UNIT[j]})</span></td>'
          f'<td style="padding:4px 0;text-align:right">{holder}{note}</td></tr>')
    A("</table>")

    # standings
    A('<h2 style="font-size:15px;margin:22px 0 8px">General Classification</h2>')
    A('<table style="border-collapse:collapse;font-size:14px;width:100%">')
    lead = min(v["sec"] for v in cur["gc"].values()) if cur["gc"] else 0
    for n in sorted(cur["gc"], key=lambda x: cur["gc"][x]["pos"]):
        g = cur["gc"][n]
        mv = next((m for m in d["movers"] if m["name"] == n), None)
        if mv:
            arrow = "&#9650;" if mv["up"] else "&#9660;"
            col = "#0a7d3c" if mv["up"] else "#c8102e"
            move = (f' <span style="color:{col};font-size:12px">{arrow} '
                    f'{abs(mv["to"] - mv["from"])}</span>')
        else:
            move = ' <span style="color:#a0a0aa;font-size:12px">&ndash;</span>'
        gap = "" if g["sec"] == lead else f' <span style="color:#6d6d78">+{fmt_clock(g["sec"] - lead)}</span>'
        A(f'<tr><td style="padding:4px 0;width:34px;color:#6d6d78">{g["pos"]}</td>'
          f'<td style="padding:4px 0"><b>{n}</b>{move}</td>'
          f'<td style="padding:4px 0;text-align:right">{fmt_clock(g["sec"])}{gap}</td></tr>')
    A("</table>")

    # the week's riding
    A('<h2 style="font-size:15px;margin:22px 0 8px">'
      + ("Season so far" if d["baseline"] else "This week") + "</h2>")
    A('<table style="border-collapse:collapse;font-size:14px;width:100%">')
    A('<tr style="color:#6d6d78;font-size:12px"><td>Rider</td>'
      '<td style="text-align:right">Miles</td><td style="text-align:right">Climbed</td>'
      '<td style="text-align:right">Rides</td></tr>')
    for w in sorted(d["week"], key=lambda x: -x["miles"]):
        quiet = (w["rides"] == 0)
        style = ';color:#a0a0aa' if quiet else ''
        A(f'<tr><td style="padding:4px 0{style}">{w["name"]}</td>'
          f'<td style="padding:4px 0;text-align:right{style}">{w["miles"]:,.1f}</td>'
          f'<td style="padding:4px 0;text-align:right{style}">{w["feet"]:,.0f} ft</td>'
          f'<td style="padding:4px 0;text-align:right{style}">{w["rides"]}</td></tr>')
    A("</table>")

    if d["prs"]:
        A('<h2 style="font-size:15px;margin:22px 0 8px">New segment bests</h2><ul '
          'style="font-size:14px;padding-left:18px;margin:0">')
        for x in d["prs"]:
            if x["first"]:
                A(f'<li style="margin:5px 0"><b>{x["name"]}</b> set a first time on '
                  f'<b>{x["seg"]}</b>: {x["time"]}</li>')
            else:
                A(f'<li style="margin:5px 0"><b>{x["name"]}</b> took '
                  f'{fmt_clock(x["gain"])} off <b>{x["seg"]}</b>: '
                  f'{x["time"]} <span style="color:#6d6d78">(was {x["was"]})</span></li>')
        A("</ul>")

    if d["tried"]:
        A('<h2 style="font-size:15px;margin:22px 0 8px">Tried and failed</h2><ul '
          'style="font-size:14px;padding-left:18px;margin:0;color:#4a4a55">')
        for x in d["tried"]:
            n = x["tries"]
            times = "once" if n == 1 else f"{n} times"
            tail = f' and did not beat {x["best"]}' if x["best"] else ""
            A(f'<li style="margin:5px 0"><b>{x["name"]}</b> hit '
              f'<b>{x["seg"]}</b> {times}{tail}</li>')
        A("</ul>")

    if d["power"]:
        A('<h2 style="font-size:15px;margin:22px 0 8px">New power bests</h2><ul '
          'style="font-size:14px;padding-left:18px;margin:0">')
        for x in d["power"]:
            was = f' <span style="color:#6d6d78">(was {x["was"]} W)</span>' if x["was"] else ""
            A(f'<li style="margin:5px 0"><b>{x["name"]}</b> {x["window"]}: '
              f'{x["watts"]} W{was}</li>')
        A("</ul>")

    if not d["baseline"] and not (d["prs"] or d["tried"] or d["power"]
                                 or any(w["rides"] for w in d["week"])):
        A('<p style="font-size:14px;color:#6d6d78;margin-top:20px">Nobody rode '
          'anything that counted this week. Standings unchanged.</p>')

    A('<p style="margin-top:26px;font-size:13px;color:#6d6d78">'
      'Everything is scoped to the '
      f'{cur["year"]} season. '
      '<a href="https://tourdesocal.com" style="color:#fc5200">tourdesocal.com</a></p>')
    A("</div>")
    return "\n".join(p)


def main():
    state = json.load(open(STATE))
    meta = json.load(open(META))
    year = datetime.date.today().strftime("%Y")
    cur = build_current(state, meta, year)

    prev = None
    if os.path.exists(SNAP):
        try:
            loaded = json.load(open(SNAP))
            # only diff against a snapshot from the same season
            if loaded.get("year") == year:
                prev = loaded
        except Exception as e:
            print(f"snapshot unreadable, treating as baseline: {e}")

    d = diff(cur, prev)
    week_end = datetime.date.today().strftime("%b %d, %Y").replace(" 0", " ")
    body = render(cur, d, week_end)

    open(EMAIL_HTML, "w").write(body)
    json.dump({"generated": week_end, "baseline": d["baseline"], "diff": d},
              open(OUT_JSON, "w"), indent=2)

    page = (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        f"<title>Week ending {week_end} &middot; Tour de SoCal</title>"
        "<link rel=\"icon\" href=\"favicon.ico\" sizes=\"any\">"
        "<style>body{background:#f6f6f8;margin:0;padding:28px 16px}</style>"
        "</head><body>" + body + "</body></html>")
    open(OUT_HTML, "w").write(page)

    # snapshot for next week: drop the display-only fields
    snap = {"taken_utc": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "year": year,
            "riders": {n: {k: v for k, v in r.items() if k != "times"}
                       for n, r in cur["riders"].items()},
            "gc": cur["gc"], "jerseys": cur["jerseys"]}
    json.dump(snap, open(SNAP, "w"), indent=2)

    print(f"digest for week ending {week_end}: "
          f"baseline={d['baseline']} movers={len(d['movers'])} prs={len(d['prs'])} "
          f"tried={len(d['tried'])} power={len(d['power'])} jerseys={len(d['jerseys'])}")


if __name__ == "__main__":
    main()
