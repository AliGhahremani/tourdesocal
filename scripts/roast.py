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
                "best": worst["best"] or ""}))
        elif total >= 2:
            hooks.append(("failed_soft", 55, {
                "who": who, "seg": worst["seg"], "n": worst["tries"]}))

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
    tried_names = {t["name"] for t in d["tried"]} | {p["name"] for p in d["prs"]}
    for w in active:
        if w["name"] not in tried_names and w["miles"] > max(60.0, med):
            hooks.append(("no_segments", 60, {
                "who": w["name"], "mi": f"{w['miles']:,.0f}"}))

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
        "{who} hit {seg} {n} times this week and beat exactly none of them. The segment is fine. {who} is fine. The times are not.",
        "Special mention to {who}, who attacked {seg} {n} separate times and still could not get under {best}. Persistence is a virtue. Results are better.",
        "{who} went at {seg} {n} times. {best} stands. At some point that stops being training and starts being a hobby.",
        "{n} attempts at {seg} by {who}, zero improvements. Somebody check the brakes are not rubbing.",
    ],
    "failed_hard_notime": [
        "{who} has now attacked {seg} {n} times without ever finishing one worth recording. That is commitment to the bit.",
        "{n} goes at {seg} from {who} and still no time on the board. The segment remains undefeated and slightly bored.",
    ],
    "failed_soft": [
        "{who} had {n} cracks at {seg} and came away with nothing. There is always next week.",
        "{seg} beat {who} {n} times this week. Not dramatic, just quietly humiliating.",
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
    "A remarkably quiet week. No PRs, no attempts, no movement. Six cyclists, "
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
GROUPED = {
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
            names = [e[1]["who"] for e in entries]
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
