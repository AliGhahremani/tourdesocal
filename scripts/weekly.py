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
import json, os, re, sys, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from roast import blurb, headline
from assess import assess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(ROOT, "data", "state.json")
META = os.path.join(ROOT, "data", "meta.json")
SNAP = os.path.join(ROOT, "data", "weekly_snapshot.json")
OUT_JSON = os.path.join(ROOT, "data", "weekly_latest.json")
OUT_HTML = os.path.join(ROOT, "weekly.html")
ARCHIVE = os.path.join(ROOT, "weekly")   # one file per email actually sent
EMAIL_HTML = "/tmp/weekly_email.html"

PENALTY = 1.10
M_PER_MI = 1609.344
FT_PER_M = 3.280839895


def fmt_gap(sec):
    """A margin. Under a minute reads as seconds, because "0:08" does not."""
    sec = int(round(sec))
    return f"{sec} seconds" if sec < 60 else fmt_clock(sec)


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
            "time_s": int(y.get("time_s") or 0),
            "vtime_s": int(y.get("vtime_s") or 0),
            "vrides": int(y.get("vrides") or 0),
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
         "tried": [], "power": [], "jerseys": [],
         "segs": {"added": [], "removed": [], "known": False},
         "koms": []}
    names = sorted(cur["riders"], key=lambda n: cur["gc"][n]["pos"])

    if prev is None:
        for n in names:
            r = cur["riders"][n]
            d["week"].append({"name": n, "miles": r["dist_m"] / M_PER_MI,
                              "feet": r["elev_m"] * FT_PER_M, "rides": r["rides"]})
        return d

    pr_r = prev.get("riders", {})
    pr_gc = prev.get("gc", {})

    # Segment leadership. Who is fastest on each segment is the thing riders
    # actually care about week to week, and until now the digest never said.
    # Both sides are computed from bests, so no new snapshot field is needed.
    def leader(pool, sid):
        """Fastest rider on a segment, or (None, sec) when it is a dead heat.

        Nobody holds a segment they are only equal fastest on, so a tie has no
        holder. Without this, min() picks one of them arbitrarily and the
        digest reports a takeover in a week where nothing changed.
        """
        got = {n: b[sid] for n, b in pool.items() if sid in b}
        if not got:
            return None, None
        best = min(got.values())
        top = [n for n, v in got.items() if v == best]
        return (top[0] if len(top) == 1 else None), best

    now_b = {n: cur["riders"][n]["bests"] for n in cur["riders"]}
    old_b = {n: (pr_r.get(n) or {}).get("bests") or {} for n in cur["riders"]}
    lead_now, lead_was = {}, {}
    for sid in cur["seg_ids"]:
        lead_now[sid] = leader(now_b, sid)
        lead_was[sid] = leader(old_b, sid)
        (who_n, sec_n), (who_w, sec_w) = lead_now[sid], lead_was[sid]
        if who_n and who_n != who_w:
            d["koms"].append({
                "seg": cur["seg_name"].get(sid, sid), "id": sid,
                "to": who_n, "from": who_w,
                "time": cur["riders"][who_n]["times"].get(sid, fmt_clock(sec_n)),
                "by": (sec_w - sec_n) if sec_w is not None else None,
            })

    # The segment list itself can change between weeks, and when it does it
    # moves everybody's GC. A snapshot taken before this was tracked has no
    # seg_ids, and "unknown" is reported as no change rather than as a list of
    # twenty one brand new segments.
    old_ids = prev.get("seg_ids")
    if old_ids is not None:
        old_names = prev.get("seg_names") or {}
        old_set, new_set = set(old_ids), set(cur["seg_ids"])
        d["segs"]["known"] = True
        d["segs"]["added"] = [{"id": sid, "name": cur["seg_name"].get(sid, sid)}
                              for sid in cur["seg_ids"] if sid not in old_set]
        d["segs"]["removed"] = [{"id": sid, "name": old_names.get(sid, sid)}
                                for sid in old_ids if sid not in new_set]

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
            who_lead, sec_lead = lead_now.get(sid, (None, None))
            took = bool(who_lead) and who_lead == n \
                and (lead_was.get(sid) or (None,))[0] != n
            gap = (new - sec_lead) if (new is not None and sec_lead is not None) else None
            # level with the fastest time is not "behind" it
            behind = gap if (gap is not None and gap > 0) else None
            common = {"name": n, "seg": seg, "id": sid, "tries": new_att,
                      "leader": who_lead if behind is not None else None,
                      "behind": behind, "took": took}
            if new is not None and (old is None or new < old):
                d["prs"].append({**common,
                                 "time": r["times"].get(sid, fmt_clock(new)),
                                 "was": fmt_clock(old) if old else None,
                                 "gain": (old - new) if old else None,
                                 "first": old is None})
            else:
                d["tried"].append({**common, "best": r["times"].get(sid)})

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


def on_the_table(cur):
    """What each rider would gain by riding segments they have skipped.

    A DNS is scored at the slowest finisher plus ten percent, so a segment you
    have not ridden this year is nearly always costing you more than riding it badly
    would. This works out how much, using each rider's own typical pace
    relative to whoever holds the segment, not a fantasy.

    Returns [(name, total_seconds_available, best_segment, best_seconds)],
    biggest first, only for riders with something material to gain.
    """
    riders = cur["riders"]
    # each rider's median ratio to the segment winner, over segments they ride
    ratios = {n: [] for n in riders}
    for sid in cur["seg_ids"]:
        got = {n: r["bests"][sid] for n, r in riders.items() if sid in r["bests"]}
        if len(got) < 2:
            continue
        best = min(got.values())
        for n, sec in got.items():
            ratios[n].append(sec / best)

    rows = []
    for name, r in riders.items():
        vals = sorted(ratios[name])
        if not vals:
            continue
        k = vals[len(vals) // 2]
        total, pick, pick_gain = 0, None, 0
        for sid in cur["seg_ids"]:
            if sid in r["bests"]:
                continue
            got = [x["bests"][sid] for x in riders.values() if sid in x["bests"]]
            if not got:
                continue
            gain = round(max(got) * PENALTY) - round(min(got) * k)
            if gain <= 0:
                continue
            total += gain
            if gain > pick_gain:
                pick, pick_gain = cur["seg_name"].get(sid, "a segment"), gain
        if total >= 60:
            rows.append((name, total, pick, pick_gain))
    rows.sort(key=lambda x: -x[1])
    return rows


def write_archive(body, week_end, sent_date):
    """Save this digest as its own dated page and rebuild the index.

    The archive is a record of emails that were actually SENT, so the caller
    only invokes this on a real send, never on a test run. Existing pages are
    left alone; the index is rebuilt from whatever is on disk, so it can never
    drift from the files themselves.
    """
    os.makedirs(ARCHIVE, exist_ok=True)
    page = os.path.join(ARCHIVE, f"{sent_date}.html")
    open(page, "w", encoding="utf-8").write(shell(body, f"Week ending {week_end}"))
    rebuild_index()
    return page


def shell(body, title):
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{title} - Tour de SoCal</title>'
            '<style>body{margin:0;background:#f4f2ee;padding:26px 14px;'
            'font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif}'
            '.bk{max-width:640px;margin:0 auto 16px;font-size:13px}'
            '.bk a{color:#fc5200;text-decoration:none}'
            '.pg{max-width:640px;margin:0 auto;background:#fff;border:1px solid #e6e2da;'
            'border-radius:12px;padding:26px 24px}</style></head><body>'
            '<div class="bk"><a href="./">&larr; All digests</a> &middot; '
            '<a href="https://tourdesocal.com">tourdesocal.com</a></div>'
            f'<div class="pg">{body}</div></body></html>')


def rebuild_index():
    """List every archived email, newest first, from what is on disk."""
    os.makedirs(ARCHIVE, exist_ok=True)
    rows = []
    for fn in sorted(os.listdir(ARCHIVE), reverse=True):
        if not fn.endswith(".html") or fn == "index.html":
            continue
        stem = fn[:-5]
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})", stem)
        if m:
            d = datetime.date(*map(int, m.groups()))
            label = d.strftime("%b %d, %Y").replace(" 0", " ")
            if stem.endswith("-kickoff"):
                label = "Kick-off &middot; " + label
        else:
            label = stem
        rows.append(f'<li><a href="{fn}">{label}</a></li>')
    body = ("".join(rows) if rows
            else '<li style="color:#6d6d78;list-style:none">Nothing sent yet.</li>')
    open(os.path.join(ARCHIVE, "index.html"), "w", encoding="utf-8").write(
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>Weekly digests - Tour de SoCal</title>'
        '<style>body{margin:0;background:#f4f2ee;padding:34px 14px;'
        'font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;color:#1c1c20}'
        '.w{max-width:640px;margin:0 auto}h1{font-size:24px;margin:0 0 4px}'
        '.s{color:#6d6d78;font-size:14px;margin:0 0 22px}'
        'ul{list-style:none;padding:0;margin:0}'
        'li{border-top:1px solid #e6e2da}'
        'li a{display:block;padding:13px 2px;color:#1c1c20;text-decoration:none;font-size:16px}'
        'li a:hover{color:#fc5200}'
        '.bk{font-size:13px;margin-top:24px}.bk a{color:#fc5200;text-decoration:none}'
        '</style></head><body><div class="w">'
        '<h1>Weekly digests</h1>'
        '<p class="s">Every email sent to the riders, as it was sent.</p>'
        f'<ul>{body}</ul>'
        '<p class="bk"><a href="https://tourdesocal.com">&larr; tourdesocal.com</a></p>'
        '</div></body></html>')


def render(cur, d, week_end, note, head=None, cards=None):
    """One HTML body used for both the email and the archive page."""
    C = {"yellow": "#d9a400", "polka": "#c8102e", "green": "#0a7d3c"}
    JN = {"yellow": "Yellow", "polka": "Polka Dot", "green": "Green"}
    UNIT = {"yellow": "GC", "polka": "elevation", "green": "miles"}
    p = []
    A = p.append

    A('<div style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;'
      'max-width:640px;margin:0 auto;color:#16161d;line-height:1.5">')
    A(f'<h1 style="font-size:22px;margin:0 0 2px">Tour de SoCal</h1>')
    A(f'<div style="color:#6d6d78;font-size:13px;margin-bottom:'
      f'{"10px" if head else "22px"}">Week ending {week_end}</div>')
    if head:
        A(f'<div style="font-size:19px;font-weight:700;line-height:1.25;'
          f'margin:0 0 16px">{head}</div>')

    # The blurb. Everything in it is earned by something in the numbers below.
    A('<div style="background:#fff6e5;border:1px solid #f0d9a8;padding:14px 16px;'
      'border-radius:10px;font-size:14.5px;line-height:1.6">' + note + '</div>')

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

    table = on_the_table(cur)
    if table:
        A('<h2 style="font-size:15px;margin:22px 0 8px">On the table</h2>')
        A('<p style="font-size:13px;color:#6d6d78;margin:0 0 8px">'
          'What you would save by riding segments you have skipped, at your own '
          'usual pace. A segment with no time on it this year is scored at the '
          'slowest time '
          'plus ten percent.</p>')
        A('<table style="border-collapse:collapse;font-size:14px;width:100%">')
        A('<tr style="color:#6d6d78;font-size:12px"><td>Rider</td>'
          '<td style="text-align:right">Available</td>'
          '<td style="padding-left:10px">Best single ride</td></tr>')
        for name, total, pick, gain in table:
            A(f'<tr><td style="padding:4px 0;border-top:1px solid #eee">{name}</td>'
              f'<td style="padding:4px 0;border-top:1px solid #eee;text-align:right">'
              f'<b>{fmt_clock(total)}</b></td>'
              f'<td style="padding:4px 0 4px 10px;border-top:1px solid #eee;color:#6d6d78">'
              f'{pick} ({fmt_clock(gain)})</td></tr>')
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

    if d["koms"]:
        A('<h2 style="font-size:15px;margin:22px 0 8px">Segments that changed '
          'hands</h2>')
        A('<div style="background:#fff1f2;border:1px solid #f3ccd1;'
          'border-radius:10px;padding:12px 15px;font-size:14px;line-height:1.6">')
        for x in d["koms"]:
            if x["from"]:
                by = f' by {fmt_gap(x["by"])}' if x.get("by") else ""
                A(f'<div style="margin:3px 0"><b>{x["to"]}</b> took '
                  f'<b>{x["seg"]}</b> off {x["from"]}{by}, in {x["time"]}.</div>')
            else:
                A(f'<div style="margin:3px 0"><b>{x["to"]}</b> is first on '
                  f'<b>{x["seg"]}</b> with {x["time"]}, the only time set on it '
                  f'this year.</div>')
        A("</div>")

    if d["prs"]:
        A('<h2 style="font-size:15px;margin:22px 0 8px">New segment bests</h2><ul '
          'style="font-size:14px;padding-left:18px;margin:0">')
        for x in d["prs"]:
            if x["took"]:
                tail = ' <span style="color:#0a7d3c">and now leads it</span>'
            elif x["behind"] is not None:
                tail = (f' <span style="color:#6d6d78">still {fmt_gap(x["behind"])} '
                        f'behind {x["leader"]}</span>')
            else:
                tail = ""
            if x["first"]:
                A(f'<li style="margin:5px 0"><b>{x["name"]}</b> set a first time on '
                  f'<b>{x["seg"]}</b>: {x["time"]}{tail}</li>')
            else:
                A(f'<li style="margin:5px 0"><b>{x["name"]}</b> took '
                  f'{fmt_gap(x["gain"])} off <b>{x["seg"]}</b>: '
                  f'{x["time"]} <span style="color:#6d6d78">(was {x["was"]})</span>'
                  f'{tail}</li>')
        A("</ul>")

    if d["tried"]:
        A('<h2 style="font-size:15px;margin:22px 0 8px">Tried and failed</h2><ul '
          'style="font-size:14px;padding-left:18px;margin:0;color:#4a4a55">')
        for x in d["tried"]:
            n = x["tries"]
            times = {1: "once", 2: "twice"}.get(n, f"{n} times")
            tail = f' and did not beat {x["best"]}' if x["best"] else ""
            if x["behind"] is not None:
                tail += (f', still {fmt_gap(x["behind"])} off '
                         f'{x["leader"]}')
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

    # Segment changes. When the list itself moves, every GC total moves with
    # it, so this goes above the assessments rather than buried at the end.
    if d["segs"]["added"] or d["segs"]["removed"]:
        A('<h2 style="font-size:15px;margin:26px 0 8px">Changes to the segment '
          'list</h2>')
        A('<div style="background:#eef4fb;border:1px solid #cfdff0;'
          'border-radius:10px;padding:13px 15px;font-size:14px;line-height:1.6">')
        for x in d["segs"]["added"]:
            A(f'<div style="margin:3px 0"><b style="color:#0a7d3c">Added</b> '
              f'{x["name"]}. Anyone without a time on it is now carrying a DNS '
              f'there.</div>')
        for x in d["segs"]["removed"]:
            A(f'<div style="margin:3px 0"><b style="color:#c8102e">Removed</b> '
              f'{x["name"]}. Times set on it no longer count towards anything.</div>')
        A('<div style="margin-top:8px;color:#4a4a55">Every GC total in this '
          'email has been recalculated over the new list, so gaps will have '
          'moved for reasons that have nothing to do with this week\'s riding.'
          '</div></div>')

    # Individual assessments. Everyone gets one every week, in GC order, so
    # the man in yellow reads his first and the man in last reads his last.
    if cards:
        A('<h2 style="font-size:15px;margin:26px 0 8px">Individual assessments, '
          'delivered without affection</h2>')
        for i, (nm, txt) in enumerate(cards):
            bg = "#faf8f4" if i % 2 == 0 else "#ffffff"
            A(f'<div style="background:{bg};border:1px solid #e6e2da;'
              f'border-radius:10px;padding:13px 15px;margin:0 0 8px;'
              f'font-size:14px;line-height:1.62">'
              f'<div style="font-family:ui-monospace,SFMono-Regular,Menlo,monospace;'
              f'font-size:12px;letter-spacing:.08em;color:#fc5200;margin-bottom:5px">'
              f'{nm.upper()}</div>{txt}</div>')

    # Ali's standing request. A good share of the DNS penalties on this site
    # are people riding straight past a tracked segment unaware it was there.
    A('<div style="margin-top:26px;padding:14px 16px;background:#fdf6e0;'
      'border-left:4px solid #e8b400;border-radius:0 8px 8px 0;'
      'font-size:13.5px;line-height:1.6;color:#2a2a2e">'
      '<strong>Stop missing segments by accident.</strong> Two minutes, once:'
      '<br><br>'
      f'<strong>1.</strong> Star all {len(cur["seg_ids"])} segments on Strava. '
      'They are all linked from the site. Starred segments sync to your head unit.'
      '<br>'
      '<strong>2.</strong> Turn on Live Segments on your Garmin or Wahoo. '
      'It warns you before one starts and counts you down through it, so you '
      'know you are on the clock instead of finding out on Sunday.'
      '<br><br>'
      'A segment you never knew you were riding is scored as a DNS, and a DNS '
      'costs the slowest time plus ten percent.'
      '</div>')

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
    today = datetime.date.today()
    week_end = today.strftime("%b %d, %Y").replace(" 0", " ")
    week_no = today.isocalendar()[1] + today.isocalendar()[0] * 100
    note = blurb(cur, d, prev, week_no)
    print("blurb:", note)
    head = headline(cur, d, prev, week_no)
    print("headline:", head)

    # Season closes at the end of December 31, so that day counts.
    days_left = (datetime.date(today.year, 12, 31) - today).days + 1
    seen = (prev or {}).get("assess_seen") or {}
    said = (prev or {}).get("assess_said") or {}
    cards, seen, said = assess(cur, meta, d, week_no, days_left, seen,
                               seeded=bool((prev or {}).get("seeded")), said=said)
    for nm, txt in cards:
        print(f"  [{nm}] {txt}")

    body = render(cur, d, week_end, note, head, cards)

    open(EMAIL_HTML, "w").write(body)
    json.dump({"generated": week_end, "baseline": d["baseline"],
               "blurb": note, "diff": d}, open(OUT_JSON, "w"), indent=2)

    page = (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        f"<title>Week ending {week_end} &middot; Tour de SoCal</title>"
        "<link rel=\"icon\" href=\"favicon.ico\" sizes=\"any\">"
        "<style>body{background:#f6f6f8;margin:0;padding:28px 16px}</style>"
        "</head><body>" + body + "</body></html>")
    open(OUT_HTML, "w").write(page)

    # Archive this digest as its own dated page and rebuild the index. A test
    # run writes it too, but weekly.yml only commits on a real send, so what
    # ends up in the repo stays a record of emails that actually went out.
    write_archive(body, week_end, datetime.date.today().isoformat())

    # snapshot for next week: drop the display-only fields
    snap = {"taken_utc": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "year": year,
            "riders": {n: {k: v for k, v in r.items() if k != "times"}
                       for n, r in cur["riders"].items()},
            "gc": cur["gc"], "jerseys": cur["jerseys"],
            "assess_seen": seen, "assess_said": said,
            "seg_ids": list(cur["seg_ids"]),
            "seg_names": dict(cur["seg_name"])}
    json.dump(snap, open(SNAP, "w"), indent=2)

    print(f"digest for week ending {week_end}: "
          f"baseline={d['baseline']} movers={len(d['movers'])} prs={len(d['prs'])} "
          f"tried={len(d['tried'])} power={len(d['power'])} jerseys={len(d['jerseys'])}")


if __name__ == "__main__":
    main()
