#!/usr/bin/env python3
"""The weekly blurb for tourdesocal.com.

Finds the stories in the week's numbers and writes them up with some attitude.
Everything here is deterministic given (week number, data), so the same week
always reads the same, but the phrasing rotates so it does not get stale.

No API and no key. It picks from real observations, not canned filler: every
line has to be earned by something in the data.

House rules for anything added here: aim at effort, laziness, indoor riding and
bad tactics. Never at anyone's body, ability to afford kit, job, family or
anything they cannot change by riding their bike more.
"""
import random

M_PER_MI = 1609.344
FT_PER_M = 3.280839895


def _ts(n):
    """once / twice / N times, so a template never says "1 cracks"."""
    return {1: "once", 2: "twice"}.get(n, f"{n} times")


def _gap(sec):
    sec = int(round(sec))
    if sec < 60:
        return f"{sec} second{'' if sec == 1 else 's'}"
    m, r = divmod(sec, 60)
    return f"{m}:{r:02d}"


def _hrs(sec):
    h = sec / 3600.0
    return f"{h:.0f}" if h >= 10 else f"{h:.1f}"


def _pick(rng, options, **kw):
    return rng.choice(options).format(**kw)


def build_hooks(cur, d, prev):
    """Every story the data supports, most interesting first."""
    hooks = []
    week = {w["name"]: w for w in d["week"]}
    riders = cur["riders"]
    active = [w for w in d["week"] if w["rides"] > 0]
    med = 0.0
    if active:
        ms = sorted(w["miles"] for w in active)
        med = ms[len(ms) // 2]

    # ---- jersey changes are the biggest news there is ----
    JN = {"yellow": "the yellow jersey", "polka": "the polka dot",
          "green": "the green jersey"}
    JC = {"yellow": "The yellow jersey", "polka": "The polka dot",
          "green": "The green jersey"}
    for j in d["jerseys"]:
        ctx = {"who": j["to"], "jersey": JN[j["jersey"]], "Jersey": JC[j["jersey"]]}
        if j["from"]:
            hooks.append(("jersey_steal", 100, dict(ctx, **{"from": j["from"]})))
        else:
            hooks.append(("jersey_first", 70, ctx))

    # ---- GC movement ----
    for m in d["movers"]:
        places = abs(m["to"] - m["from"])
        hooks.append(("moved_up" if m["up"] else "moved_down", 60 + places * 5,
                      {"who": m["name"], "places": places,
                       "s": "" if places == 1 else "s", "to": m["to"]}))

    # ---- tried and failed, the best material there is ----
    by_rider = {}
    for t in d["tried"]:
        by_rider.setdefault(t["name"], []).append(t)
    for who, items in by_rider.items():
        worst = max(items, key=lambda x: x["tries"])
        total = sum(x["tries"] for x in items)
        if worst["tries"] >= 3:
            # Two shapes: one for someone defending a time, one for someone who
            # has attacked it repeatedly and never set a time at all.
            kind = "failed_hard" if worst["best"] else "failed_hard_notime"
            hooks.append((kind, 90, {
                "who": who, "seg": worst["seg"], "n": worst["tries"],
                "times": _ts(worst["tries"]), "best": worst["best"] or ""}))
        elif total >= 2:
            hooks.append(("failed_soft", 55, {
                "who": who, "seg": worst["seg"], "n": worst["tries"],
                "times": _ts(worst["tries"])}))

    # ---- did not ride at all ----
    for w in d["week"]:
        if w["rides"] == 0 and not d["baseline"]:
            hooks.append(("zero", 85, {"who": w["name"]}))
        elif active and w["miles"] > 0 and med > 0 and w["miles"] < med * 0.4:
            hooks.append(("lazy", 50, {
                "who": w["name"], "mi": f"{w['miles']:,.0f}",
                "med": f"{med:,.0f}"}))

    # ---- indoor time this week ----
    if prev:
        for name, r in riders.items():
            pv = (prev.get("riders", {}).get(name) or {})
            vt = int(r.get("vtime_s") or 0) - int(pv.get("vtime_s") or 0)
            tt = int(r.get("time_s") or 0) - int(pv.get("time_s") or 0)
            if vt >= 3 * 3600 and tt > 0 and vt / tt > 0.6:
                hooks.append(("zwift", 80, {"who": name, "hrs": _hrs(vt)}))
            elif vt >= 6 * 3600:
                hooks.append(("zwift_some", 45, {"who": name, "hrs": _hrs(vt)}))

    # ---- big week ----
    if active:
        top = max(active, key=lambda w: w["miles"])
        if med > 0 and top["miles"] > med * 1.8:
            hooks.append(("big_week", 65, {
                "who": top["name"], "mi": f"{top['miles']:,.0f}",
                "ft": f"{top['feet']:,.0f}"}))
        climb = max(active, key=lambda w: w["feet"])
        if climb["feet"] > 8000:
            hooks.append(("big_climb", 55, {
                "who": climb["name"], "ft": f"{climb['feet']:,.0f}"}))

    # ---- miles but no segments ----
    # A seeded snapshot carries this week's segment bests already, so segment
    # efforts before the seed date are invisible. Claiming nobody rode one
    # would be a lie, so skip the accusation for that one week.
    seeded = bool((prev or {}).get("seeded"))
    tried_names = {t["name"] for t in d["tried"]} | {p["name"] for p in d["prs"]}
    if not seeded:
        for w in active:
            if w["name"] not in tried_names and w["miles"] > max(60.0, med):
                hooks.append(("no_segments", 60, {
                    "who": w["name"], "mi": f"{w['miles']:,.0f}"}))

    # ---- segments changing hands ----
    # The biggest thing that can happen in a week. Outranks every PR, because
    # a PR that beats nobody and a PR that takes a segment are not the same
    # story and the digest used to report them identically.
    for x in (d.get("koms") or []):
        if x.get("from"):
            hooks.append(("kom_change", 95, {
                "who": x["to"], "seg": x["seg"], "from": x["from"],
                "time": x["time"],
                "by": _gap(x["by"]) if x.get("by") else "a matter of seconds"}))
        else:
            hooks.append(("kom_first", 80, {
                "who": x["to"], "seg": x["seg"], "time": x["time"]}))

    # ---- attacked it, still not theirs ----
    for x in (d.get("tried") or []) + (d.get("prs") or []):
        if x.get("behind") is None or x.get("took"):
            continue
        if x["behind"] <= 20:
            hooks.append(("so_close", 72, {
                "who": x["name"], "seg": x["seg"],
                "owner": x["leader"] or "the fastest time",
                "gap": _gap(x["behind"])}))

    # ---- PRs ----
    for x in d["prs"]:
        if x["first"]:
            hooks.append(("first_time", 45, {"who": x["name"], "seg": x["seg"]}))
        elif x["gain"] and x["gain"] >= 20:
            hooks.append(("big_pr", 75, {
                "who": x["name"], "seg": x["seg"], "sec": int(x["gain"]),
                "time": x["time"]}))
        elif x["gain"] and x["gain"] <= 2:
            hooks.append(("tiny_pr", 50, {
                "who": x["name"], "seg": x["seg"], "sec": int(x["gain"]),
                "s": "" if x["gain"] == 1 else "s"}))

    # ---- the grinder: hammering a segment they still do not own ----
    # attempts are counted per segment for the season. Someone with a pile of
    # them and no KOM is a story, and it is the one bit of collected data the
    # site has never used.
    best_by_seg = {}
    for name, r in riders.items():
        for sid, sec in r["bests"].items():
            if sid not in best_by_seg or sec < best_by_seg[sid][1]:
                best_by_seg[sid] = (name, sec)
    for name, r in riders.items():
        worst = None
        for sid, n_att in (r.get("attempts") or {}).items():
            if not n_att or n_att < 4:
                continue
            owner = best_by_seg.get(sid)
            if not owner or owner[0] == name:
                continue
            if worst is None or n_att > worst[1]:
                worst = (sid, n_att, owner[0])
        if worst:
            sid, n_att, owner = worst
            hooks.append((
                "grinder", 48, {"who": name, "seg": cur["seg_name"].get(sid, "that segment"),
                                "n": n_att, "times": _ts(n_att), "owner": owner}))

    # ---- season long shame: never touched a tracked segment ----
    for name, r in riders.items():
        if not r["bests"] and not d["baseline"]:
            hooks.append(("no_segments_ever", 40, {"who": name}))

    # ---- rode, but nothing worth writing home about ----
    # Every rider has to get a mention, so this is the fallback material.
    for w in d["week"]:
        if w["rides"] > 0:
            hooks.append(("unremarkable", 5, {
                "who": w["name"], "mi": f"{w['miles']:,.0f}",
                "ft": f"{w['feet']:,.0f}", "n": w["rides"],
                "s": "" if w["rides"] == 1 else "s"}))

    # ---- power ----
    for x in d["power"]:
        if x["was"] and x["watts"] - x["was"] >= 15:
            hooks.append(("power", 45, {
                "who": x["name"], "w": x["watts"], "win": x["window"]}))

    hooks.sort(key=lambda h: -h[1])
    return hooks


LINES = {
    "jersey_steal": [
        "{who} took {jersey} off {from}. Somewhere {from} is refreshing the page and pretending not to care.",
        "{Jersey} has a new owner. {who} takes it, {from} hands it over. That is how this works.",
        "{from} held {jersey} right up until {who} decided otherwise.",
        "Changing of the guard: {who} now wears {jersey}. {from} may collect their belongings.",
    ],
    "jersey_first": [
        "{who} is the first to actually own {jersey}. Low bar, still counts.",
        "{Jersey} finally has a name on it and it is {who}.",
    ],
    "moved_up": [
        "{who} climbed {places} place{s} on GC. Quietly, like someone with a plan.",
        "{who} is up {places} place{s}. Whatever they are doing, it is working.",
        "{who} moved up {places} place{s} to {to}. The rest of you noticed, right?",
    ],
    "moved_down": [
        "{who} slid {places} place{s} down the GC without touching a bike wrong. Just got out-ridden.",
        "{who} dropped {places} place{s}. Not from riding badly, from other people riding at all.",
        "Down {places} place{s} for {who}, who is learning that standings move whether you do or not.",
    ],
    "failed_hard": [
        "{who} hit {seg} {times} this week and beat exactly none of them. The segment is fine. {who} is fine. The times are not.",
        "Special mention to {who}, who attacked {seg} {n} separate times and still could not get under {best}. Persistence is a virtue. Results are better.",
        "{who} went at {seg} {times}. {best} stands. At some point that stops being training and starts being a hobby.",
        "{n} attempts at {seg} by {who}, zero improvements. Somebody check the brakes are not rubbing.",
    ],
    "failed_hard_notime": [
        "{who} has now attacked {seg} {times} without ever finishing one worth recording. That is commitment to the bit.",
        "{n} goes at {seg} from {who} and still no time on the board. The segment remains undefeated and slightly bored.",
    ],
    "failed_soft": [
        "{who} went at {seg} {times} and came away with nothing. There is always next week.",
        "{seg} beat {who} {times} this week. Not dramatic, just quietly humiliating.",
    ],
    "zero": [
        "{who} put in zero miles this week. Not a slow week. Zero. Someone go and knock on the door.",
        "No rides at all from {who}. The bike is presumably still in the garage, gathering meaning.",
        "{who} recorded nothing this week. We are choosing to believe the head unit broke.",
        "Zero miles for {who}. That is a bold tactical choice with the standings this tight.",
    ],
    "lazy": [
        "{who} managed {mi} miles while everyone else averaged {med}. We are not angry, just taking notes.",
        "{mi} miles for {who} against a group median of {med}. Comfortable week.",
        "{who} contributed {mi} miles to the cause. The cause noticed.",
    ],
    "zwift": [
        "Someone check on {who}, who spent {hrs} hours this week riding a screen. There is real road outside and it is free.",
        "{who} logged {hrs} hours indoors. That is not a training block, that is a hostage situation. Go and be a good friend.",
        "{hrs} hours of virtual riding from {who}. The sun was out. It was right there.",
        "{who} did {hrs} hours in the pain cave. Watopia is not a real place and those are not real hills.",
    ],
    "zwift_some": [
        "{who} put {hrs} hours into the trainer this week. Respect the commitment, question the location.",
        "{hrs} indoor hours for {who}. Whatever gets it done, apparently.",
    ],
    "big_week": [
        "{who} put in {mi} miles and {ft} feet this week and made the rest of the group look like a recovery ride.",
        "Biggest week goes to {who}: {mi} miles, {ft} feet. Show off.",
        "{mi} miles for {who}. At some point this stops being a hobby and starts being a problem.",
    ],
    "big_climb": [
        "{who} climbed {ft} feet this week. The polka dot does not defend itself.",
        "{ft} feet of climbing from {who}, who has clearly decided gravity is a personal matter.",
    ],
    "no_segments": [
        "{who} rode {mi} miles this week and did not attempt a single tracked segment. Beautiful ride. Zero points.",
        "{mi} miles from {who}, none of them anywhere near a segment that counts. Impressive commitment to the scenic route.",
        "{who} covered {mi} miles avoiding every segment on the list. That takes planning.",
    ],
    "first_time": [
        "{who} finally put a time on {seg}. Only took most of the year.",
        "First recorded effort on {seg} from {who}. It exists now.",
    ],
    "big_pr": [
        "{who} took {sec} seconds off {seg} and set {time}. That is a proper improvement, not a rounding error.",
        "{sec} seconds off {seg} for {who}. Something has changed and the rest of you should be worried.",
    ],
    "tiny_pr": [
        "{who} improved {seg} by {sec} second{s}. We are contractually obliged to call that a PR.",
        "A whole {sec} second{s} off {seg} for {who}. Frame it.",
    ],
    "kom_change": [
        "{who} took {seg} off {from} by {by}, {time}. That one has a new owner.",
        "{seg} belongs to {who} now. {time}, {by} clear of {from}.",
        "{from} held {seg} coming into this week and does not hold it now. {who} went {time}.",
    ],
    "kom_first": [
        "{who} is first on {seg} with {time}, the only time anybody has put on it.",
    ],
    "so_close": [
        "{who} went at {seg} and finished {gap} behind {owner}. Close enough to hurt.",
        "{gap} is all that stood between {who} and {owner} on {seg}.",
        "{who} came within {gap} of {owner} on {seg} and no closer.",
    ],
    "grinder": [
        "{who} has now hit {seg} {times} this season and {owner} still owns it. At some point that stops being persistence.",
        "{who} has gone at {seg} {times}, and the record is still {owner}'s. Admirable. Ineffective, but admirable.",
        "Nobody has attacked {seg} more often than {who} this season, {times}, and nobody has less to show for it. {owner} thanks you for the traffic.",
    ],
    "no_segments_ever": [
        "{who} still has not put a time on a single tracked segment this season. The segments are listed on the site. With maps.",
        "Season to date, {who} has attempted zero of the tracked segments. Genuinely impressive avoidance.",
    ],
    "unremarkable": [
        "{who} quietly did {mi} miles over {n} ride{s}. No drama, no headlines, no complaints.",
        "{who} put in {mi} miles and {ft} feet without troubling the standings either way.",
        "A steady, forgettable week from {who}: {mi} miles, {n} ride{s}, nothing to see.",
        "{who} rode {mi} miles and kept out of trouble. We will allow it.",
    ],
    "silent": [
        "Not a single data point from {who} this week. Presumed alive.",
        "{who} contributed nothing measurable. Not even a bad ride.",
        "{who} remains a theoretical participant.",
    ],
    "power": [
        "{who} put out {w} W for {win}. Someone has been eating their vegetables.",
        "New {win} best from {who} at {w} W. Suspiciously good.",
    ],
}

OPENERS = [
    "Right, the week in review.",
    "Let us see what everyone got up to.",
    "Weekly reckoning time.",
    "Here is how the week actually went.",
    "The numbers are in and they are talking.",
    "Another week, another set of receipts.",
]

QUIET = [
    "Nothing happened this week. Nobody rode anything that counted, nothing moved, "
    "and the standings are exactly where you left them. Do better.",
    "A remarkably quiet week. No PRs, no attempts, no movement. Five cyclists, "
    "collectively, achieved nothing measurable.",
    "The week produced no news whatsoever. Either everyone is tapering for "
    "something or everyone has given up.",
]

BASELINE = [
    "First digest, so no roasting yet. These are the season totals as they stand. "
    "From next week the numbers get compared and the commentary starts.",
]


# When several riders earn the same hook in one week, saying it four times in a
# row reads like a bug. These collapse the group into one line instead.
# Every template in here is formatted with {names} and {n} and NOTHING else.
# A per rider key in this dict raises KeyError the first week three riders
# qualify, which is a long way from where the mistake was made.
GROUPED = {
    "so_close": [
        "{names} all went at segments this week and all came up short of the man holding them.",
        "{n} riders attacked something they do not own and {n} riders failed to take it. {names}.",
    ],
    "grinder": [
        "{names} are all hammering away at segments somebody else owns. {n} riders, plenty of attempts, no records.",
        "{names} have each spent the season attacking a segment they still do not hold.",
    ],
    "zero": [
        "{names} put in nothing at all this week. Between them, {n} riders and zero miles.",
        "{names} all recorded zero. That is {n} bikes gathering dust simultaneously.",
        "No rides whatsoever from {names}. A coordinated effort, if nothing else.",
    ],
    "no_segments": [
        "{names} all rode plenty and attempted not one tracked segment. Lovely rides. No points.",
        "{names} between them covered real distance while carefully avoiding every segment that counts.",
    ],
    "lazy": [
        "{names} all came in well under the group average. Not naming and shaming, just naming.",
    ],
    "no_segments_ever": [
        "{names} still have not set a time on a single tracked segment all season.",
    ],
}


def _join(names):
    names = list(names)
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return ", ".join(names[:-1]) + f" and {names[-1]}"


HEADLINES = {
    "jersey_steal":  "{who} takes {jersey} from {from}",
    "jersey_first":  "{who} takes {jersey}",
    "moved_up":      "{who} moves up {places} place{s}",
    "moved_down":    "{who} drops {places} place{s}",
    "big_pr":        "{who} resets {seg}",
    "tiny_pr":       "{who} shaves {sec}s off {seg}",
    "big_week":      "{who} put in {mi} miles",
    "big_climb":     "{who} went up {ft} feet",
    "zwift":         "{who} spent the week indoors",
    "zero":          "{who} did not ride",
    "power":         "{who} sets a new power best",
    "grinder":       "{who} attacks {seg} again",
    "first_time":    "{who} finally rides {seg}",
    "no_segments":   "A week without a single segment",
    "failed_soft":   "{who} tried {seg} and came up short",
    "kom_change":    "{who} takes {seg} off {from}",
    "kom_first":     "{who} is first on {seg}",
    "so_close":      "{who} misses {seg} by {gap}",
}


def headline(cur, d, prev, week_no):
    """The single biggest thing that happened, as a short header.

    The blurb already varies its wording. This makes the digest vary its
    SHAPE too: whatever mattered most leads the email, so a week where a
    jersey changed hands does not open the same way as a week nobody rode.
    Returns None when there is nothing worth a headline.
    """
    if d["baseline"]:
        return None
    hooks = build_hooks(cur, d, prev)
    if not hooks:
        return None
    for kind, score, ctx in sorted(hooks, key=lambda h: -h[1]):
        tpl = HEADLINES.get(kind)
        if not tpl:
            continue
        try:
            return tpl.format(**ctx)   # ctx keys include "from", fine for str.format
        except (KeyError, IndexError):
            continue
    return None


def _selftest():
    """Every template must be formattable from the ctx its dict is called with.

    A missing key here surfaces as a KeyError inside a Sunday workflow run,
    long after the edit that caused it, and kills the digest. Checking it at
    import time costs nothing.
    """
    import string
    def keys(t):
        return {f for _, f, _, _ in string.Formatter().parse(t) if f}
    bad = []
    for kind, tpls in GROUPED.items():
        for t in tpls:
            extra = keys(t) - {"names", "n"}
            if extra:
                bad.append(f"GROUPED[{kind!r}] uses {sorted(extra)}, "
                           f"but grouped lines only get names and n")
    for kind in HEADLINES:
        if kind not in LINES:
            bad.append(f"HEADLINES[{kind!r}] has no matching LINES entry")
    if bad:
        raise AssertionError("roast.py template mismatch:\n  " + "\n  ".join(bad))


_selftest()


def blurb(cur, d, prev, week_no):
    """A paragraph about the week. Every rider gets a mention, and nothing is
    said that the numbers do not support."""
    rng = random.Random(week_no * 7919 + len(cur["riders"]))

    if d["baseline"]:
        return rng.choice(BASELINE)

    everyone = list(cur["riders"].keys())
    hooks = build_hooks(cur, d, prev)
    if not hooks:
        return rng.choice(QUIET) + " " + _join(everyone) + ", all of you."

    by_kind = {}
    for kind, score, ctx in hooks:
        by_kind.setdefault(kind, []).append((score, ctx))

    items = []  # (score, kind, ctx, grouped, covers)
    for kind, entries in by_kind.items():
        if len(entries) >= 3 and kind in GROUPED:
            # One rider can qualify twice for the same kind, for instance two
            # near misses in a week, and listing them twice reads as a bug
            # because it is one. Keep first appearance order.
            names, seen_n = [], set()
            for e in entries:
                w = e[1].get("who")
                if w and w not in seen_n:
                    seen_n.add(w)
                    names.append(w)
            if len(names) < 3:
                for score, ctx in entries:
                    who = ctx.get("who")
                    items.append((score, kind, ctx, False, {who} if who else set()))
                continue
            items.append((entries[0][0] + 5, kind,
                          {"names": _join(names), "n": len(names)}, True, set(names)))
        else:
            for score, ctx in entries:
                who = ctx.get("who")
                items.append((score, kind, ctx, False, {who} if who else set()))
    items.sort(key=lambda x: -x[0])

    chosen, used_kinds, covered = [], set(), set()

    # Pass one: the best story per rider, juiciest first, one line per person.
    for score, kind, ctx, grouped, covers in items:
        if kind in used_kinds and not grouped:
            continue
        if covers and covers <= covered:
            continue
        chosen.append((kind, ctx, grouped))
        used_kinds.add(kind)
        covered |= covers

    # Pass two: anyone still unmentioned gets their best remaining line, even a
    # dull one. Better a boring sentence than being left out of the group chat.
    for name in everyone:
        if name in covered:
            continue
        pick = next((it for it in items if name in it[4]), None)
        if pick:
            chosen.append((pick[1], pick[2], pick[3]))
            covered.add(name)
        else:
            chosen.append(("silent", {"who": name}, False))
            covered.add(name)

    out = [rng.choice(OPENERS)]
    for kind, ctx, grouped in chosen:
        pool = GROUPED[kind] if grouped else LINES[kind]
        out.append(_pick(rng, pool, **ctx))
    return " ".join(out)
