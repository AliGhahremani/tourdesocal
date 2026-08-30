#!/usr/bin/env python3
"""Per-rider paragraphs for the Sunday digest.

Everyone gets a paragraph every week: what they did in the seven days just
gone, then one or two observations drawn from where they actually stand in
the season, then a close.

The hard part is not writing one good paragraph, it is writing eighteen of
them for the same five people without repeating. A week on its own is thin
material: three rides and maybe no segment at all. So each paragraph pairs
the week with a SEASON angle, and the angles rotate. Every rider carries a
short memory of which angles they have already had, stored in the weekly
snapshot, and an angle cannot come back around until several others have had
a turn.

Nothing in here is invented. Every sentence is formatted from a number that
came out of state.json, and any angle whose data is missing is simply not
offered that week.
"""
import datetime
import random
import sys


def _join(names):
    """Ali / Ali and Jake / Ali, Jake and Randee. Empty is a real case."""
    names = list(names)
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return ", ".join(names[:-1]) + f" and {names[-1]}"

M_PER_MI = 1609.344
FT_PER_M = 3.280839895
PENALTY = 1.10

# How many recent angles a rider remembers. An angle used this week is pushed
# to the back of the queue until this many others have had a turn.
MEMORY = 9
# And how many recent SENTENCES, so an angle that does come back around comes
# back worded differently. Nobody should read the same line twice in a season.
SAID = 14


def _clock(sec):
    sec = int(round(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _mins(sec):
    """A gap, said the way a cyclist says it."""
    sec = int(round(sec))
    if sec < 60:
        return f"{sec} seconds"
    return _clock(sec)


def _n(x):
    return f"{x:,.0f}"


def _times(n):
    return {1: "once", 2: "twice"}.get(n, f"{_w(n)} times")


def _plural(n, one, many=None):
    return one if n == 1 else (many or one + "s")


WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six",
         7: "seven", 8: "eight", 9: "nine", 10: "ten", 11: "eleven",
         12: "twelve", 13: "thirteen", 14: "fourteen", 15: "fifteen",
         16: "sixteen", 17: "seventeen", 18: "eighteen", 19: "nineteen",
         20: "twenty", 21: "twenty one"}


def _w(n):
    return WORDS.get(n, str(n))


ORD = {1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth",
       6: "sixth", 7: "seventh", 8: "eighth"}


def _o(n):
    return ORD.get(n, f"{n}th")


# --------------------------------------------------------------------------
# facts
# --------------------------------------------------------------------------

def season_facts(cur, meta, days_left, segs=None, d=None, elapsed_days=1):
    """Everything true about each rider's season, computed once."""
    riders = cur["riders"]
    seg_ids = cur["seg_ids"]
    seg_name = cur["seg_name"]

    grade = {}
    length = {}
    for s in (meta.get("segments") or []):
        sid = str(s["id"])
        try:
            grade[sid] = float(str(s.get("grade", "")).rstrip("%"))
        except ValueError:
            pass
        try:
            length[sid] = float(str(s.get("dist", "")).split()[0])
        except (ValueError, IndexError):
            pass

    koms, lasts, ratios = {n: [] for n in riders}, {n: [] for n in riders}, {n: [] for n in riders}
    for sid in seg_ids:
        got = {n: r["bests"][sid] for n, r in riders.items() if sid in r["bests"]}
        if not got:
            continue
        best = min(got.values())
        for n, sec in got.items():
            ratios[n].append(sec / best)
        # Everyone on the fastest time holds it. A dead heat is joint first,
        # and index.html has always counted it that way.
        for n, sec in got.items():
            if sec == best:
                koms[n].append(sid)
        if len(got) >= 3:
            lasts[max(got, key=got.get)].append(sid)

    # raw power ranks, best first, per duration
    PWR = {"300": "five minute", "600": "ten minute", "1200": "twenty minute",
           "1800": "half hour", "3600": "one hour"}
    pranks = {}
    for k in PWR:
        vals = [(n, r["power"].get(k)) for n, r in riders.items() if r["power"].get(k)]
        vals.sort(key=lambda kv: -kv[1])
        for i, (n, v) in enumerate(vals):
            pranks.setdefault(n, {})[k] = (i + 1, v, len(vals))

    gone_kom = {}
    for x in ((segs or {}).get("removed") or []):
        sid = x["id"]
        got = {n: r["bests"][sid] for n, r in riders.items() if sid in r["bests"]}
        if got:
            b = min(got.values())
            for n, sec in got.items():
                if sec == b:
                    gone_kom.setdefault(n, set()).add(sid)

    order = sorted(cur["gc"], key=lambda n: cur["gc"][n]["pos"])
    lead_sec = cur["gc"][order[0]]["sec"] if order else 0
    by_miles = sorted(riders, key=lambda n: -riders[n]["dist_m"])
    by_feet = sorted(riders, key=lambda n: -riders[n]["elev_m"])

    F = {}
    for name, r in riders.items():
        pos = cur["gc"][name]["pos"]
        vals = sorted(ratios[name])
        k = vals[len(vals) // 2] if vals else None

        skipped = []
        for sid in seg_ids:
            if sid in r["bests"]:
                continue
            got = [x["bests"][sid] for x in riders.values() if sid in x["bests"]]
            if not got:
                continue
            gain = round(max(got) * PENALTY) - (round(min(got) * k) if k else 0)
            skipped.append((sid, max(gain, 0)))
        skipped.sort(key=lambda x: -x[1])

        # a segment attacked repeatedly and still not owned
        grind = None
        for sid, att in sorted(r["attempts"].items(), key=lambda kv: -kv[1]):
            if att >= 4 and sid in seg_ids and sid not in koms[name]:
                got = {n: x["bests"][sid] for n, x in riders.items() if sid in x["bests"]}
                if got:
                    grind = (sid, att, min(got, key=got.get))
                    break

        miles = r["dist_m"] / M_PER_MI
        feet = r["elev_m"] * FT_PER_M
        F[name] = {
            "pos": pos, "sec": cur["gc"][name]["sec"],
            "to_lead": cur["gc"][name]["sec"] - lead_sec,
            "ahead": order[pos - 2] if pos >= 2 else None,
            "ahead_gap": (cur["gc"][name]["sec"] - cur["gc"][order[pos - 2]]["sec"]) if pos >= 2 else None,
            "behind": order[pos] if pos < len(order) else None,
            "behind_gap": (cur["gc"][order[pos]]["sec"] - cur["gc"][name]["sec"]) if pos < len(order) else None,
            "koms": koms[name], "lasts": lasts[name],
            # scoped to the segments actually in play: state.json can still
            # carry bests for segments that have since left the list
            "ridden": sum(1 for sid in seg_ids if sid in r["bests"]),
            "total_segs": len(seg_ids),
            "skipped": skipped, "grind": grind, "ratio": k,
            "miles": miles, "feet": feet, "rides": r["rides"],
            "hours": r["time_s"] / 3600.0,
            "vhours": r["vtime_s"] / 3600.0,
            "vshare": (r["vtime_s"] / r["time_s"]) if r["time_s"] else 0.0,
            "fpm": (feet / miles) if miles else 0.0,
            "attempts": sum(r["attempts"].get(s, 0) for s in seg_ids),
            "power": pranks.get(name, {}),
            "miles_rank": by_miles.index(name) + 1,
            "feet_rank": by_feet.index(name) + 1,
            "miles_gap": (riders[by_miles[0]]["dist_m"] - r["dist_m"]) / M_PER_MI,
            "feet_gap": (riders[by_feet[0]]["elev_m"] - r["elev_m"]) * FT_PER_M,
            "grade": grade, "length": length, "seg_name": seg_name,
            "days_left": days_left, "year": cur["year"],
            # This week measured against the rider's own average week, which is
            # the fairest yardstick: 30 miles is a normal week for one man and a
            # week off for another. Ali's note, 2026-08-28: the roasting had gone
            # soft and the biggest sitting target of the week went unmentioned.
            "wk_miles": 0.0, "wk_feet": 0.0, "wk_rides": 0,
            "avg_week": (miles / max(1.0, elapsed_days / 7.0)) if miles else 0.0,
            "seg_added": (segs or {}).get("added") or [],
            "seg_removed": (segs or {}).get("removed") or [],
            # this week's segment news, already computed by weekly.diff
            "took": [k for k in ((d or {}).get("koms") or [])
                     if name in k["to"] and name not in (k.get("from") or [])],
            "lost_to": [k for k in ((d or {}).get("koms") or [])
                        if name in (k.get("from") or []) and name not in k["to"]],
            "near": [{"seg": x["seg"], "leader": x["leader"],
                      "behind": x["behind"], "tries": x["tries"],
                      "pr": pr}
                     for pr, pool in ((True, (d or {}).get("prs") or []),
                                      (False, (d or {}).get("tried") or []))
                     for x in pool
                     if x["name"] == name and x.get("behind") is not None],
            "name": name,
            "have": dict(r["bests"]),
            "was_kom": set(koms[name]) | gone_kom.get(name, set()),
        }

    field_fpm = sorted(v["fpm"] for v in F.values())
    med_fpm = field_fpm[len(field_fpm) // 2] if field_fpm else 0
    for v in F.values():
        v["med_fpm"] = med_fpm
    return F


# --------------------------------------------------------------------------
# angles
# --------------------------------------------------------------------------
# Each returns (score, [phrasings]) or None when the data does not support it.
# Higher score means more interesting. The phrasings exist so the same angle
# reads differently the second time a rider gets it.

def _a_koms(f, s):
    n = len(f["koms"])
    if n < 2:
        return None
    names = [f["seg_name"].get(i, "") for i in f["koms"][:2]]
    return 70, [
        f"You are fastest on {_w(n)} segments, and {names[0]} is one of them.",
        f"{_w(n).capitalize()} segments on this site are yours until somebody "
        f"goes quicker.",
        f"Nobody has beaten you on {_w(n)} of the {_w(f['total_segs'])}.",
    ]


def _a_no_koms(f, s):
    n = len(f["koms"])
    if n > 1 or f["ridden"] < 8:
        return None
    if n == 1:
        return 68, [
            f"One segment out of {_w(f['ridden'])} ridden has your name on it. One.",
            f"You have ridden {_w(f['ridden'])} segments and you are fastest on exactly one of them.",
        ]
    return 74, [
        f"{_w(f['ridden']).capitalize()} segments ridden and not one of them is yours.",
        f"You do not hold a single segment on this site, off {_w(f['ridden'])} attempts at owning one.",
    ]


def _a_lasts(f, s):
    n = len(f["lasts"])
    if n < 2:
        return None
    seg = f["seg_name"].get(f["lasts"][0], "")
    return 66, [
        f"You are also the slowest man on {_w(n)} segments, {seg} among them.",
        f"{_w(n).capitalize()} segments have you at the bottom of the sheet.",
        f"The other side of it: {_w(n)} last places, more time given away than you probably think.",
    ]


def _a_never(f, s):
    """Segments with no time THIS SEASON.

    Everything on this site is scoped to the competition year, and no rider
    has meaningful history before it, so we do not know and must not claim
    that anyone has never ridden a road in their life. What the data supports
    is "not in {year}", and that is what these say.
    """
    n = len(f["skipped"])
    if n < 1:
        return None
    top = f["seg_name"].get(f["skipped"][0][0], "")
    gain = f["skipped"][0][1]
    yr = f["year"]
    if n == 1:
        return 78, [
            f"One segment stands between you and the full set this year: {top}. "
            f"Riding it once is worth about {_mins(gain)} to your GC.",
            f"You have ridden everything except {top} in {yr}. That single "
            f"omission is costing you roughly {_mins(gain)}.",
        ]
    return 76, [
        f"There are {_w(n)} segments you have not ridden this year, and the worst "
        f"of them is {top} at about {_mins(gain)} of free time.",
        f"{_w(n).capitalize()} segments still have no {yr} time against your name. "
        f"{top} alone is worth {_mins(gain)} to you, and it is not going to ride itself.",
        f"Still {_w(n)} on the list you have not been down this season. Start with "
        f"{top}: {_mins(gain)}, one afternoon.",
        f"{top} is the single most expensive thing you are not doing, at roughly "
        f"{_mins(gain)}, and it is one of {_w(n)} you have skipped all year.",
        f"Your {yr} blank list is {_w(n)} deep. {top} sits on top of it holding "
        f"{_mins(gain)} of your time hostage.",
        f"{_w(n).capitalize()} segments with no time on them this year. Not slow "
        f"times, no times. {top} is the one that costs you most, at about {_mins(gain)}.",
    ]


def _a_steep(f, s):
    steeps = [(sid, f["grade"].get(sid, 0)) for sid, _ in f["skipped"]]
    steeps = [x for x in steeps if x[1] >= 12]
    if len(steeps) < 2:
        return None
    steeps.sort(key=lambda x: -x[1])
    a = f["seg_name"].get(steeps[0][0], "")
    b = f["seg_name"].get(steeps[1][0], "")
    return 72, [
        f"Look at which ones you are skipping. {a} at {steeps[0][1]:.0f} percent and "
        f"{b} at {steeps[1][1]:.0f} percent are both missing from your year. "
        f"That is not a scheduling accident.",
        f"The gradients tell on you: {a} and {b}, the two steepest things you have "
        f"avoided, at {steeps[0][1]:.0f} and {steeps[1][1]:.0f} percent.",
    ]


def _a_table(f, s):
    total = sum(g for _, g in f["skipped"])
    if total < 120:
        return None
    return 73, [
        f"Add up everything you are giving away by not riding the segments you skip "
        f"and it comes to about {_mins(total)}. That is not training, that is paperwork.",
        f"About {_mins(total)} is sitting on the table for you, and all of it is in "
        f"segments you have simply not ridden this year.",
    ]


def _a_grind(f, s):
    if not f["grind"]:
        return None
    sid, att, owner = f["grind"]
    seg = f["seg_name"].get(sid, "")
    return 69, [
        f"You have been at {seg} {_w(att)} times this year and {owner} still owns it.",
        f"{_w(att).capitalize()} runs at {seg} and it is still {owner}'s. "
        f"At some point that stops being persistence.",
        f"{seg} has taken {_w(att)} attempts off you and given nothing back. "
        f"{owner} has not had to defend it once.",
    ]


def _a_fpm(f, s):
    if f["miles"] < 200 or not f["med_fpm"]:
        return None
    r = f["fpm"] / f["med_fpm"]
    if r >= 1.25:
        return 60, [
            f"You climb {_n(f['fpm'])} feet for every mile you ride, the hardest "
            f"ratio on the board. Nobody is picking easier roads than you.",
            f"{_n(f['fpm'])} feet per mile. You do not ride flat and it shows.",
        ]
    if r <= 0.78:
        return 64, [
            f"{_n(f['fpm'])} feet per mile is the flattest riding here. "
            f"There is a version of your season with the same miles and real climbing in it.",
            f"Your climbing works out to {_n(f['fpm'])} feet a mile, well under the field. "
            f"The miles are there. The elevation is a choice.",
        ]
    return None


def _a_indoor(f, s):
    if f["hours"] < 20 or f["vshare"] < 0.18:
        return None
    pct = round(f["vshare"] * 100)
    return 62, [
        f"{pct} percent of your saddle time this year was indoors, "
        f"{_n(f['vhours'])} hours of it. It counts, but it does not win segments.",
        f"{_n(f['vhours'])} of your {_n(f['hours'])} hours were virtual. "
        f"No segment on this site has ever been set on a trainer.",
    ]


def _a_volume(f, s):
    if f["rides"] < 60:
        return None
    if f["miles_rank"] == 1 or f["feet_rank"] == 1:
        return 63, [
            f"{_w(f['rides']) if f['rides'] < 16 else _n(f['rides'])} rides and "
            f"{_n(f['hours'])} hours. You out-work this field by simply refusing to stop.",
            f"{_n(f['rides'])} rides, {_n(f['hours'])} hours, top of the pile on volume. "
            f"That is a season nobody can argue with.",
        ]
    return 52, [
        f"{_n(f['rides'])} rides and {_n(f['hours'])} hours in the bank. "
        f"Nobody is going to accuse you of not turning up.",
        f"{_n(f['rides'])} rides this year. The consistency is real even when "
        f"the results are not.",
    ]


def _a_ahead(f, s):
    if not f["ahead"] or not f["ahead_gap"]:
        return None
    return 71, [
        f"{f['ahead']} is {_mins(f['ahead_gap'])} up the road in {_o(f['pos'] - 1)}. "
        f"That is one good segment, not a rebuild.",
        f"You are {_mins(f['ahead_gap'])} off {f['ahead']}. "
        f"With {f['days_left']} days left that is a gap you close by riding, "
        f"not by hoping.",
        f"The only man you actually have to beat is {f['ahead']}, and he is "
        f"{_mins(f['ahead_gap'])} ahead. Everything past him is a bonus.",
        f"{_mins(f['ahead_gap'])} to {f['ahead']}. Say that out loud and it stops "
        f"sounding like a lot.",
        f"You sit {_o(f['pos'])}, {_mins(f['ahead_gap'])} behind {f['ahead']}. "
        f"Nobody is going to hand you that.",
    ]


def _a_behind(f, s):
    if not f["behind"] or not f["behind_gap"] or f["behind_gap"] > 900:
        return None
    return 67, [
        f"{f['behind']} is {_mins(f['behind_gap'])} behind you and closing is easier "
        f"than defending. Do not get comfortable.",
        f"Check your mirrors. {f['behind']} sits {_mins(f['behind_gap'])} back.",
    ]


def _a_yellow(f, s):
    if f["pos"] == 1 or not f["to_lead"]:
        return None
    return 65, [
        f"Yellow is {_mins(f['to_lead'])} away. Not close, not impossible.",
        f"{_mins(f['to_lead'])} covers the whole gap to the race lead.",
    ]


def _a_leader(f, s):
    if f["pos"] != 1:
        return None
    gap = f["behind_gap"]
    if not gap:
        return None
    return 75, [
        f"You are in yellow with {_mins(gap)} on {f['behind']}, and every week you "
        f"do not extend it is a week somebody else gets closer.",
        f"The jersey is yours by {_mins(gap)}. Leading in August is not the same as "
        f"leading on December 31.",
    ]


def _a_green(f, s):
    if f["miles_rank"] == 1 or f["miles_gap"] > 400:
        return None
    return 70, [
        f"You are {_n(f['miles_gap'])} miles off green. That is a fortnight of "
        f"deciding to go outside.",
        f"Green is {_n(f['miles_gap'])} miles up the road. Nothing technical about it.",
    ]


def _a_polka(f, s):
    if f["feet_rank"] == 1 or f["feet_gap"] > 25000:
        return None
    return 70, [
        f"Polka dot sits {_n(f['feet_gap'])} feet away, which is a handful of "
        f"proper days in the hills.",
        f"{_n(f['feet_gap'])} feet of climbing separates you from the polka dot jersey.",
    ]


def _a_power(f, s):
    best = None
    LBL = {"300": "five minutes", "600": "ten minutes", "1200": "twenty minutes",
           "1800": "half an hour", "3600": "a full hour"}
    for k, (rank, watts, n) in f["power"].items():
        if rank == 1 and n >= 3:
            best = (k, watts, n)
            break
    if not best:
        return None
    k, watts, n = best
    return 58, [
        f"Best {LBL.get(k, k)} power in the field at {watts} watts. "
        f"The engine is not what is holding you back.",
        f"{watts} watts for {LBL.get(k, k)}, top of the board. "
        f"Nobody here can out-push you over that.",
    ]


def _a_spread(f, s):
    if f["attempts"] < 60 or f["ridden"] < 1:
        return None
    per = f["attempts"] / f["ridden"]
    if per < 6:
        return None
    return 61, [
        f"{_n(f['attempts'])} segment attempts across {_w(f['ridden'])} segments. "
        f"You are riding the same ground over and over instead of the ground you are missing.",
        f"{_n(f['attempts'])} attempts, but only {_w(f['ridden'])} distinct segments. "
        f"Volume in the wrong direction.",
    ]


def _a_complete(f, s):
    left = f["total_segs"] - f["ridden"]
    if left != 0:
        return None
    return 72, [
        f"All {_w(f['total_segs'])} segments ridden this year. Whatever else is "
        f"true, nobody can say you dodged anything.",
        f"A complete {f['year']} card: {_w(f['total_segs'])} of "
        f"{_w(f['total_segs'])}. No penalty time anywhere in your total.",
    ]


def _a_new_seg(f, s):
    """A segment joined the list this week and this rider has no time on it.

    This is the only angle that can appear out of nowhere with no riding
    involved, so it outranks everything: the rider woke up with a penalty
    they did not earn.
    """
    fresh = [x for x in f["seg_added"] if x["id"] not in f["have"]]
    if not fresh:
        return None
    names = ", ".join(x["name"] for x in fresh[:2])
    if len(fresh) == 1:
        return 90, [
            f"{names} joined the list this week and you have no time on it, "
            f"so you are carrying a DNS there from today. Cheapest fix on your "
            f"whole card: ride it once.",
            f"New this week: {names}. You have not been down it this year, "
            f"which means it is already costing you penalty time.",
            f"{names} is on the board as of this week and your name is not on "
            f"it. That is a penalty you acquired by doing nothing at all.",
            f"The list gained {names} and you have no {f['year']} time there. "
            f"Ride it once and the penalty goes away.",
            f"Fresh liability: {names}. Added this week, unridden by you, "
            f"scored against you until that changes.",
        ]
    return 90, [
        f"{_w(len(fresh)).capitalize()} segments joined the list this week, "
        f"{names} among them, and you have a time on none of them. That is "
        f"penalty time you picked up without turning a pedal.",
    ]


def _a_new_seg_done(f, s):
    """Added this week, and this rider already had a qualifying ride on it."""
    got = [x for x in f["seg_added"] if x["id"] in f["have"]]
    if not got:
        return None
    x = got[0]
    mine = f["have"].get(x["id"])
    return 86, [
        f"{x['name']} was added to the list this week and you already had a "
        f"time on it, {_clock(mine)}. Free position on a segment you did not "
        f"know you were racing.",
        f"Lucky week: {x['name']} joined the list and your {_clock(mine)} on it "
        f"counts retroactively. Everyone without one is now behind.",
        f"Your {_clock(mine)} on {x['name']} was worth nothing last Sunday and "
        f"is worth something today. The list grew to include it.",
        f"{x['name']} is new to the board this week. You had already been down "
        f"it in {_clock(mine)}, so you start that one with a time on the sheet.",
        f"Nothing you did earned this: {x['name']} joined the list and your "
        f"existing {_clock(mine)} came with it.",
    ]


def _a_lost_kom(f, s):
    """A segment this rider was fastest on has left the list."""
    lost = [x for x in f["seg_removed"] if x["id"] in f["was_kom"]]
    if not lost:
        return None
    x = lost[0]
    return 88, [
        f"{x['name']} came off the list this week and you were the fastest man "
        f"on it. That one is gone and it is not coming back.",
        f"Bad news aimed squarely at you: {x['name']} has been removed, and it "
        f"was yours. Everyone else lost a segment. You lost a win.",
        f"You held {x['name']} outright and this week it stopped counting. "
        f"Nobody took it off you, which somehow makes it worse.",
    ]


def _a_lost_dns(f, s):
    """A segment this rider was being penalised on has left the list."""
    saved = [x for x in f["seg_removed"] if x["id"] not in f["have"]]
    if not saved:
        return None
    x = saved[0]
    return 84, [
        f"{x['name']} left the list this week and you had no time on it, "
        f"so a penalty just quietly came off your total. Do not get used to it.",
        f"You got away with one: {x['name']} is off the list and you were "
        f"carrying a DNS on it.",
        f"{x['name']} has been removed. You were being penalised on it and now "
        f"you are not, which is the laziest time you will gain all year.",
        f"One fewer thing to avoid: {x['name']} is off the board and you never "
        f"did ride it.",
    ]


def _a_took_kom(f, s):
    """This rider became fastest on a segment this week. The best news there is."""
    if not f["took"]:
        return None
    x = f["took"][0]
    prev = _join(x["from"]) if x.get("from") else None
    mates = [m for m in x["to"] if m != f["name"]] if isinstance(x.get("to"), list) else []
    by = f" by {_mins(x['by'])}" if x.get("by") else ""
    if prev and mates:
        return 96, [
            f"You and {_join(mates)} both went {x['time']} on {x['seg']}, which "
            f"takes it off {prev} and leaves the pair of you joint fastest. "
            f"Nobody owns it outright until one of you goes quicker.",
            f"{x['seg']} is yours and {_join(mates)}'s, dead level on {x['time']}, "
            f"and {prev} is out of it.",
        ]
    if prev:
        return 96, [
            f"You took {x['seg']} off {prev}{by}, in {x['time']}. "
            f"That segment is yours until somebody comes and gets it.",
            f"{x['seg']} is yours. {x['time']}, {by.strip() or 'clear'} of "
            f"{prev}, who held it coming into this week.",
            f"The headline from your week: {prev} no longer owns {x['seg']}. "
            f"You do, on {x['time']}.",
        ]
    if x.get("with"):
        held = _join(x["with"])
        return 94, [
            f"You drew level with {held} on {x['seg']}, both of you on "
            f"{x['time']}. Level is not ahead. One more second and it is yours "
            f"outright.",
            f"{x['seg']} is a dead heat now: you and {held} on {x['time']} "
            f"apiece. Neither of you owns it until one of you goes quicker.",
        ]
    return 94, [
        f"You are first on {x['seg']} with {x['time']}, the only time anybody "
        f"has set on it this year. Hold it or somebody will take it.",
    ]


def _a_kom_taken(f, s):
    """Somebody took a segment off this rider this week."""
    if not f["lost_to"]:
        return None
    x = f["lost_to"][0]
    by = f" by {_mins(x['by'])}" if x.get("by") else ""
    # a segment can change hands to two people at once, so the pronoun has to move
    many = isinstance(x.get("to"), list) and len(x["to"]) > 1
    theirs = "their" if many else "his"
    x = dict(x, to=_join(x["to"]) if isinstance(x.get("to"), list) else x.get("to"))
    return 92, [
        f"{x['to']} took {x['seg']} off you{by} this week. You held that one "
        f"coming in and you do not hold it now.",
        f"You lost {x['seg']} to {x['to']}{by}. It is {x['time']} to get it back.",
        f"{x['seg']} was yours until this week. {x['to']} went {x['time']} and "
        f"it is {theirs} problem to defend now, not yours.",
    ]


def _a_near_miss(f, s):
    """Attacked a segment this week and did not take it. Say by how much."""
    if not f["near"]:
        return None
    x = min(f["near"], key=lambda y: y["behind"])
    tries = _times(x["tries"])
    # the fastest time can be shared, in which case nobody holds the segment
    named = bool(x["leader"])
    x = dict(x, leader=x["leader"] or "the fastest time on it")
    pr = " You did take a personal best out of it." if x["pr"] else ""
    if x["behind"] <= 15:
        return 93, [
            f"You went at {x['seg']} {tries} and finished {_mins(x['behind'])} "
            f"behind {x['leader']}.{pr} That is close enough to be annoying and "
            f"close enough to fix.",
            f"{_mins(x['behind'])}. That is all that stood between you and "
            f"{x['leader']} on {x['seg']} this week.{pr}",
        ]
    out = [
        f"You attacked {x['seg']} {tries} this week and came up "
        f"{_mins(x['behind'])} short of {x['leader']}.{pr}",
        f"{x['seg']} {tries} this week, still {_mins(x['behind'])} off "
        f"{x['leader']}.{pr}",
    ]
    if named:
        # only say "he" when there is a he. A shared fastest time has no owner.
        out.append(f"{x['seg']} {tries} this week, still {_mins(x['behind'])} off "
                   f"{x['leader']}.{pr} He has not had to respond yet.")
    return 87, out


def _a_dead_level(f, s):
    who = None
    if f["ahead"] and f["ahead_gap"] == 0:
        who = f["ahead"]
    elif f["behind"] and f["behind_gap"] == 0:
        who = f["behind"]
    if not who:
        return None
    return 80, [
        f"You and {who} are dead level on GC, to the second. One segment "
        f"settles it either way.",
        f"There is nothing between you and {who}. Identical totals. "
        f"Whoever rides next wins the argument.",
    ]


def _a_slacked(f, s):
    """A week well down on the rider's own normal. The best roast material
    there is, and it was going unused: Randee rode 31 percent of his average
    week while holding two jerseys and the digest said nothing."""
    if not f["avg_week"] or f["wk_rides"] == 0:
        return None
    r = f["wk_miles"] / f["avg_week"]
    if r > 0.55:
        return None
    mi, avg = f["wk_miles"], f["avg_week"]
    pct = max(1, round(r * 100))
    return 89, [
        f"Let us talk about the {mi:,.0f} miles. You average {avg:,.0f} a week. "
        f"This was {pct} percent of a normal you, and nobody made you do that.",
        f"{mi:,.0f} miles. Your own average week is {avg:,.0f}. Whatever that was, "
        f"it was not a week of riding.",
        f"You did {pct} percent of your usual mileage this week and the standings "
        f"noticed even if nobody else did.",
        f"A {mi:,.0f} mile week from a man who normally turns in {avg:,.0f}. "
        f"The bike was right there.",
    ]


def _a_nothing(f, s):
    """Did not ride at all."""
    if f["wk_rides"] != 0:
        return None
    return 91, [
        "Zero rides. Not a slow week, not a short week. Zero.",
        "You did not get on the bike once. Everyone else did, and the gaps in "
        "this email are the receipt.",
        "Nothing at all this week. The season has a deadline and it does not "
        "care what came up.",
    ]


def _a_big_week(f, s):
    """Well above their own normal."""
    if not f["avg_week"] or f["wk_rides"] == 0:
        return None
    r = f["wk_miles"] / f["avg_week"]
    if r < 1.5:
        return None
    return 82, [
        f"{f['wk_miles']:,.0f} miles against your own {f['avg_week']:,.0f} average. "
        f"Something has got into you and the rest of them should hope it wears off.",
        f"That is {round(r*100)} percent of a normal week for you. Credit where it "
        f"is due, and a warning to everybody above you.",
    ]


def _a_pace(f, s):
    if not f["ratio"] or f["ridden"] < 6:
        return None
    pct = round((f["ratio"] - 1) * 100)
    if pct < 2:
        return None            # "within 0 percent" is not a thing to say
    if pct < 8:
        return 59, [
            f"On a typical segment you finish within {pct} percent of the fastest "
            f"time set. You are closer to the front than the table suggests.",
        ]
    if pct > 28:
        return 57, [
            f"On the average segment you are {pct} percent off the quickest time. "
            f"The gap is in the efforts, not the mileage.",
        ]
    return None


ANGLES = {
    "koms": _a_koms, "no_koms": _a_no_koms, "lasts": _a_lasts,
    "never": _a_never, "steep": _a_steep, "table": _a_table,
    "grind": _a_grind, "fpm": _a_fpm, "indoor": _a_indoor,
    "volume": _a_volume, "ahead": _a_ahead, "behind": _a_behind,
    "yellow": _a_yellow, "leader": _a_leader, "green": _a_green,
    "polka": _a_polka, "power": _a_power, "spread": _a_spread,
    "complete": _a_complete, "pace": _a_pace,
    "new_seg": _a_new_seg, "new_seg_done": _a_new_seg_done,
    "lost_kom": _a_lost_kom, "lost_dns": _a_lost_dns,
    "took_kom": _a_took_kom, "kom_taken": _a_kom_taken,
    "dead_level": _a_dead_level,
    "slacked": _a_slacked, "nothing": _a_nothing, "big_week": _a_big_week,
    "near_miss": _a_near_miss,
}

# News angles report a thing that happened this week rather than a standing
# fact, so they must never be suppressed by the rotation memory.
NEWS = {"new_seg", "new_seg_done", "lost_kom", "lost_dns",
        "took_kom", "kom_taken", "near_miss",
        "slacked", "nothing", "big_week"}

# Angles that say much the same thing. Never use two from one set in one
# paragraph, or it reads like the generator is stuck.
CLASHES = [{"koms", "no_koms"}, {"never", "steep", "table", "complete"},
           {"ahead", "yellow", "leader", "behind", "dead_level"},
           {"green", "polka"},
           {"volume", "fpm", "power"}, {"pace", "no_koms"},
           {"lasts", "no_koms"}, {"grind", "spread"},
           {"new_seg", "new_seg_done"}, {"lost_kom", "lost_dns"},
           {"new_seg", "never", "steep", "table", "complete"},
           {"took_kom", "koms"}, {"kom_taken", "no_koms", "lasts"},
           {"near_miss", "grind"},
           {"slacked", "nothing", "big_week", "volume"}]


# --------------------------------------------------------------------------
# the week
# --------------------------------------------------------------------------

def _week_opener(rng, name, wk, d, seeded):
    """What they did in the seven days just gone. Always literally true."""
    prs = [x for x in d["prs"] if x["name"] == name]
    tried = [x for x in d["tried"] if x["name"] == name]
    pwr = [x for x in d["power"] if x["name"] == name]
    mv = next((m for m in d["movers"] if m["name"] == name), None)
    jer = [j for j in d["jerseys"] if j["to"] == name]

    mi, ft, rides = wk["miles"], wk["feet"], wk["rides"]
    out = []

    if jer:
        j = {"yellow": "the yellow jersey", "polka": "the polka dot jersey",
             "green": "the green jersey"}[jer[0]["jersey"]]
        was = jer[0].get("from")
        out.append(f"You took {j} this week" + (f", off {was}." if was else "."))
    elif mv and mv["up"]:
        out.append(f"Up to {_w(mv['to'])} on GC this week, from {_w(mv['from'])}.")
    elif mv and not mv["up"]:
        out.append(f"Down to {_w(mv['to'])} on GC this week. {_w(mv['from']).capitalize()} "
                   f"was yours seven days ago.")

    if rides <= 0:
        pass                   # the "nothing" angle says this, and says it better
    else:
        out.append(f"{_w(rides).capitalize() if rides < 11 else _n(rides)} "
                   f"{_plural(rides, 'ride')}, {mi:,.0f} miles and {_n(ft)} feet.")

    # Work out which segments the ANGLES are about to cover in full, and let
    # the opener stay off them. Otherwise the paragraph describes the same
    # ride twice, once badly and once well.
    took_ids = {k["id"] for k in (d.get("koms") or []) if k["to"] == name}
    close = [x for x in prs + tried if x.get("behind") is not None]
    covered = set(took_ids)
    if close:
        covered.add(min(close, key=lambda y: y["behind"])["id"])

    rest_prs = [x for x in prs if x.get("id") not in covered]
    rest_tried = [x for x in tried if x.get("id") not in covered]

    if rest_prs:
        big = max(rest_prs, key=lambda x: x.get("gain") or 0)
        if big["first"]:
            out.append(f"First time down {big['seg']} in {big['time']}.")
        elif big.get("gain"):
            out.append(f"You took {_mins(big['gain'])} off {big['seg']}, "
                       f"down to {big['time']}.")
    elif rest_tried:
        t = rest_tried[0]
        out.append(f"You hit {t['seg']} {_times(t['tries'])} and did not improve.")
    elif not prs and not tried and rides > 0 and not seeded:
        # only claim nothing was ridden when genuinely nothing was
        out.append("No segment on the list was touched.")

    if len(prs) > 1:
        out.append(f"{_w(len(prs)).capitalize()} personal bests this week.")

    if pwr:
        p = max(pwr, key=lambda x: x["watts"])
        out.append(f"New best {p['window']} power at {p['watts']} watts.")
    return " ".join(out)


CLOSERS_LATE = [
    "{days} days left.",
    "There are {days} days in this season and no more after that.",
    "{days} days. December 31 does not negotiate.",
]
CLOSERS_MID = [
    "Plenty of season left, which is exactly why it gets wasted.",
    "There is time. There is not unlimited time.",
    "{days} days is long enough to fix this and short enough to run out.",
]


def shame_of_the_week(F, d, rng):
    """One rider, named, for the worst thing anybody did this week.

    Ali's ask, 2026-08-28. Everything here has to be earned by a number, and it
    has to be allowed to come back EMPTY: manufacturing a villain in a week when
    nobody deserves one is how a running joke dies. If no candidate clears the
    bar the digest says so, which is funnier anyway.

    Bound by the roast rules: effort, laziness, indoor riding, bad tactics.
    Never anything a rider cannot fix by riding their bike more.
    """
    picks = []
    for name, f in F.items():
        wk_mi, rides = f["wk_miles"], f["wk_rides"]

        if rides == 0:
            picks.append((100, name,
                "did not ride a bike this week",
                "Not a short week. Not a slow week. Nothing at all."))
            continue

        if f["avg_week"] and wk_mi < f["avg_week"] * 0.55:
            r = wk_mi / f["avg_week"]
            picks.append((90 + (0.55 - r) * 18, name,
                f"managed {wk_mi:,.0f} miles",
                f"His own average week is {f['avg_week']:,.0f}. That is "
                f"{max(1, round(r * 100))} percent of a normal him, and nobody "
                f"made him do it."))

        for x in f["lost_to"]:
            by = f" by {_mins(x['by'])}" if x.get("by") else ""
            who = _join(x["to"]) if isinstance(x.get("to"), list) else x["to"]
            picks.append((80, name,
                f"let {who} take {x['seg']} off him{by}",
                f"He held it coming into this week. He does not hold it now."))

        tried = [x for x in (d.get("tried") or []) if x["name"] == name]
        n_att = sum(x["tries"] for x in tried)
        if n_att >= 3 and not any(p["name"] == name for p in (d.get("prs") or [])):
            seg = max(tried, key=lambda x: x["tries"])["seg"]
            picks.append((65, name,
                f"made {n_att} attempts and improved nothing",
                f"{seg} took the worst of it. Effort is not the problem."))

    mv = [m for m in (d.get("movers") or []) if not m["up"]]
    for m in mv:
        picks.append((75, m["name"],
            f"dropped from {_o(m['from'])} to {_o(m['to'])} on GC",
            "Not from riding badly. From other people riding at all."))

    if not picks:
        return None
    top = max(p[0] for p in picks)
    best = [p for p in picks if p[0] == top]
    _, name, verdict, detail = rng.choice(best)
    return {"name": name, "verdict": verdict, "detail": detail}


def assess(cur, meta, d, week_no, days_left, seen=None, seeded=False, said=None):
    """One paragraph per rider.

    Returns ([(name, text)], updated_seen, updated_said). Both memories ride
    along in the weekly snapshot, so the rotation survives across weeks
    without any state of its own.
    """
    seen = {k: list(v) for k, v in (seen or {}).items()}
    said = {k: list(v) for k, v in (said or {}).items()}
    yr = int(cur.get("year") or 0) or datetime.date.today().year
    in_year = (datetime.date(yr, 12, 31) - datetime.date(yr, 1, 1)).days + 1
    elapsed_days = max(1, in_year - days_left + 1)
    F = season_facts(cur, meta, days_left, d.get("segs"), d, elapsed_days)
    for name, f in F.items():
        w = next((x for x in d["week"] if x["name"] == name), None)
        if w:
            f["wk_miles"], f["wk_feet"], f["wk_rides"] = w["miles"], w["feet"], w["rides"]
    wk = {w["name"]: w for w in d["week"]}
    order = sorted(cur["gc"], key=lambda n: cur["gc"][n]["pos"])

    out = []
    # Five paragraphs in one email have to say five different things, so an
    # angle another rider already got this week is heavily discouraged, and a
    # sentence already used this week is never used twice.
    week_keys, week_text, week_shape = set(), set(), set()

    for name in order:
        f = F[name]
        rng = random.Random(week_no * 104729 + sum(ord(c) for c in name) * 31)
        w = wk.get(name, {"miles": 0.0, "feet": 0.0, "rides": 0})

        # every angle the data supports this week
        avail = []
        for key, fn in ANGLES.items():
            try:
                got = fn(f, cur)
            except Exception as e:
                print(f"assess: angle {key} failed for {name}: "
                      f"{type(e).__name__}: {e}", file=sys.stderr)
                got = None
            if got:
                score, phrasings = got
                avail.append((score, key, phrasings))

        recent = seen.get(name, [])
        # An angle used recently is pushed down rather than banned outright, so
        # a rider with few angles still gets a paragraph.
        def rank(item):
            score, key, _ = item
            if key in NEWS:
                return -score          # this week's news always leads
            if key in recent:
                score -= 200 - 20 * recent.index(key)
            if key in week_keys:
                score -= 55
            return -score

        avail.sort(key=rank)

        picked, used_keys = [], []
        for score, key, phrasings in avail:
            if len(picked) >= 3:
                break
            if any(key in c and (set(used_keys) & c) for c in CLASHES):
                continue
            fresh = [(i, t) for i, t in enumerate(phrasings)
                     if t not in week_text and (key, i) not in week_shape]
            if not fresh:
                fresh = [(i, t) for i, t in enumerate(phrasings)
                         if t not in week_text]
            if not fresh:
                continue
            # prefer wording this rider has not had recently
            unheard = [x for x in fresh if x[1] not in said.get(name, [])]
            idx, line = rng.choice(unheard or fresh)
            picked.append(line)
            week_text.add(line)
            week_shape.add((key, idx))
            used_keys.append(key)
            week_keys.add(key)

        parts = [_week_opener(rng, name, w, d, seeded)]
        parts += picked

        if days_left <= 45:
            parts.append(rng.choice(CLOSERS_LATE).format(days=days_left))
        elif rng.random() < 0.4:
            parts.append(rng.choice(CLOSERS_MID).format(days=days_left))

        out.append((name, " ".join(x for x in parts if x)))

        rot = [k for k in used_keys if k not in NEWS]
        recent = rot + [k for k in recent if k not in rot]
        seen[name] = recent[:MEMORY]
        heard = picked + [t for t in said.get(name, []) if t not in picked]
        said[name] = heard[:SAID]

    shame = shame_of_the_week(F, d, random.Random(week_no * 7717))
    return out, seen, said, shame
