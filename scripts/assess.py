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
import random

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

def season_facts(cur, meta, days_left):
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
        winner = min(got, key=got.get)
        koms[winner].append(sid)
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
            "days_left": days_left,
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
        f"You hold {_w(n)} segments outright, and {names[0]} is one of them.",
        f"{_w(n).capitalize()} segments on this site are yours until somebody takes them off you.",
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
    n = len(f["skipped"])
    if n < 1:
        return None
    top = f["seg_name"].get(f["skipped"][0][0], "")
    gain = f["skipped"][0][1]
    if n == 1:
        return 78, [
            f"One segment stands between you and the full set: {top}. "
            f"Riding it once is worth about {_mins(gain)} to your GC.",
            f"You have ridden everything except {top}. That single omission is "
            f"costing you roughly {_mins(gain)}.",
        ]
    return 76, [
        f"There are {_w(n)} segments you have never ridden, and the worst of them "
        f"is {top} at about {_mins(gain)} of free time.",
        f"{_w(n).capitalize()} segments remain untouched. {top} alone is worth "
        f"{_mins(gain)} to you, and it is not going to ride itself.",
        f"Still {_w(n)} on the list you have never been down. Start with {top}: "
        f"{_mins(gain)}, one afternoon.",
        f"{top} is the single most expensive thing you are not doing, at roughly "
        f"{_mins(gain)}, and it is one of {_w(n)} you have never ridden.",
        f"Your untouched pile is {_w(n)} deep. {top} sits on top of it holding "
        f"{_mins(gain)} of your time hostage.",
        f"{_w(n).capitalize()} segments never ridden. Not slowly, not badly. "
        f"Never. {top} is the one that costs you most, at about {_mins(gain)}.",
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
        f"{b} at {steeps[1][1]:.0f} percent are both on your untouched list. "
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
        f"segments you have simply never ridden.",
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
    if not f["ahead"] or f["ahead_gap"] is None:
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
    if not f["behind"] or f["behind_gap"] is None or f["behind_gap"] > 900:
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
    if gap is None:
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
        f"All {_w(f['total_segs'])} segments ridden. Whatever else is true, "
        f"nobody can say you dodged anything.",
        f"A complete card: {_w(f['total_segs'])} of {_w(f['total_segs'])}. "
        f"No penalty time anywhere in your total.",
    ]


def _a_pace(f, s):
    if not f["ratio"] or f["ridden"] < 6:
        return None
    pct = round((f["ratio"] - 1) * 100)
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
}

# Angles that say much the same thing. Never use two from one set in one
# paragraph, or it reads like the generator is stuck.
CLASHES = [{"koms", "no_koms"}, {"never", "steep", "table", "complete"},
           {"ahead", "yellow", "leader"}, {"green", "polka"},
           {"volume", "fpm", "power"}, {"pace", "no_koms"},
           {"lasts", "no_koms"}, {"grind", "spread"}]


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
        out.append("You did not ride at all this week.")
    else:
        out.append(f"{_w(rides).capitalize() if rides < 11 else _n(rides)} "
                   f"{_plural(rides, 'ride')}, {mi:,.0f} miles and {_n(ft)} feet.")

    if prs:
        big = max(prs, key=lambda x: x.get("gain") or 0)
        if big["first"]:
            out.append(f"First time down {big['seg']} in {big['time']}.")
        elif big.get("gain"):
            out.append(f"You took {_clock(big['gain'])} off {big['seg']}, "
                       f"down to {big['time']}.")
        if len(prs) > 1:
            out.append(f"{_w(len(prs)).capitalize()} personal bests in total.")
    elif tried:
        t = tried[0]
        out.append(f"You hit {t['seg']} "
                   f"{'once' if t['tries'] == 1 else _w(t['tries']) + ' times'} "
                   f"and did not improve.")
    elif rides > 0 and not seeded:
        out.append("No segment on the list was touched.")

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


def assess(cur, meta, d, week_no, days_left, seen=None, seeded=False, said=None):
    """One paragraph per rider.

    Returns ([(name, text)], updated_seen, updated_said). Both memories ride
    along in the weekly snapshot, so the rotation survives across weeks
    without any state of its own.
    """
    seen = {k: list(v) for k, v in (seen or {}).items()}
    said = {k: list(v) for k, v in (said or {}).items()}
    F = season_facts(cur, meta, days_left)
    wk = {w["name"]: w for w in d["week"]}
    order = sorted(cur["gc"], key=lambda n: cur["gc"][n]["pos"])

    out = []
    # Five paragraphs in one email have to say five different things, so an
    # angle another rider already got this week is heavily discouraged, and a
    # sentence already used this week is never used twice.
    week_keys, week_text = set(), set()

    for name in order:
        f = F[name]
        rng = random.Random(week_no * 104729 + sum(ord(c) for c in name) * 31)
        w = wk.get(name, {"miles": 0.0, "feet": 0.0, "rides": 0})

        # every angle the data supports this week
        avail = []
        for key, fn in ANGLES.items():
            try:
                got = fn(f, cur)
            except Exception:
                got = None
            if got:
                score, phrasings = got
                avail.append((score, key, phrasings))

        recent = seen.get(name, [])
        # An angle used recently is pushed down rather than banned outright, so
        # a rider with few angles still gets a paragraph.
        def rank(item):
            score, key, _ = item
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
            fresh = [t for t in phrasings if t not in week_text]
            if not fresh:
                continue
            # prefer wording this rider has not had recently
            unheard = [t for t in fresh if t not in said.get(name, [])]
            line = rng.choice(unheard or fresh)
            picked.append(line)
            week_text.add(line)
            used_keys.append(key)
            week_keys.add(key)

        parts = [_week_opener(rng, name, w, d, seeded)]
        parts += picked

        if days_left <= 45:
            parts.append(rng.choice(CLOSERS_LATE).format(days=days_left))
        elif rng.random() < 0.4:
            parts.append(rng.choice(CLOSERS_MID).format(days=days_left))

        out.append((name, " ".join(x for x in parts if x)))

        recent = used_keys + [k for k in recent if k not in used_keys]
        seen[name] = recent[:MEMORY]
        heard = picked + [t for t in said.get(name, []) if t not in picked]
        said[name] = heard[:SAID]

    return out, seen, said
