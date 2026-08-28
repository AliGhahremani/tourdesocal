#!/usr/bin/env python3
"""Rebuild the segment map lines in data/meta.json, with a grade per point.

Pulls latlng, distance and altitude streams for every tracked segment and
rewrites meta["polylines"] and meta["grades"]. The two arrays are always the
same length for a segment, so index i of one lines up with index i of the other
and index.html can colour each piece of line by how steep it is.

One read per segment, so 22 reads for the whole set. Run it by hand from the
Actions tab when segments are added, not on a schedule. Nothing here changes
day to day, and the daily read budget is shared with 2024michael.
"""
import json, os, sys, urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from update import (ROOT, META_PATH, API, http, refresh_access_token, _rl)


def resample(alt, dist, latlng):
    """Even spacing along the segment, with a grade for each point.

    Raw GPS altitude wobbles by a metre or two between neighbouring points, and
    over a 10 m gap that wobble reads as a 20% wall. So altitude is averaged
    over roughly a 90 m window before any grade comes out of it. What is left is
    the shape of the road rather than the noise of the receiver.
    """
    total = dist[-1] - dist[0]
    if not total > 0:
        return None, None
    n = max(20, min(90, round(total / 40)))
    step = total / n

    def at(x):
        lo, hi = 0, len(dist) - 1
        while lo < hi - 1:
            mid = (lo + hi) // 2
            if dist[mid] <= x:
                lo = mid
            else:
                hi = mid
        span = (dist[hi] - dist[lo]) or 1
        f = (x - dist[lo]) / span
        return (alt[lo] + (alt[hi] - alt[lo]) * f,
                latlng[lo][0] + (latlng[hi][0] - latlng[lo][0]) * f,
                latlng[lo][1] + (latlng[hi][1] - latlng[lo][1]) * f)

    pts = [at(dist[0] + step * i) for i in range(n + 1)]
    w = max(1, round(45 / step))
    sm = []
    for i in range(len(pts)):
        lo, hi = max(0, i - w), min(len(pts), i + w + 1)
        sm.append(sum(p[0] for p in pts[lo:hi]) / (hi - lo))

    poly, grades = [], []
    for i, p in enumerate(pts):
        j = min(len(pts) - 1, i + 1)
        g = ((sm[j] - sm[i]) / step * 100) if j > i else 0.0
        poly.append([round(p[1], 4), round(p[2], 4)])
        grades.append(round(max(-30.0, min(30.0, g)), 1))
    return poly, grades


def dump(meta):
    """Same shape as before, but one line per segment for the big arrays.

    Indented per element this file is 90 KB of mostly whitespace. Per segment it
    is reviewable in a diff and a third of the size.
    """
    keys = sorted(meta["polylines"], key=int)
    segs = json.dumps(meta["segments"], indent=2)
    segs = "\n".join(l if i == 0 else "  " + l for i, l in enumerate(segs.split("\n")))
    out = ['{\n  "segments": ' + segs + ",\n  \"polylines\": {"]
    out.append(",\n".join('    "%s": %s' % (k, json.dumps(meta["polylines"][k])) for k in keys))
    out.append('  },\n  "grades": {')
    out.append(",\n".join('    "%s": %s' % (k, json.dumps(meta["grades"][k])) for k in keys))
    out.append("  }\n}")
    return "\n".join(out) + "\n"


def main():
    cid = os.environ["STRAVA_CLIENT_ID"]
    csec = os.environ["STRAVA_CLIENT_SECRET"]
    rt = next((os.environ.get(k) for k in
               ("STRAVA_REFRESH_ALI", "STRAVA_REFRESH_JAKE", "STRAVA_REFRESH_RANDEE",
                "STRAVA_REFRESH_ABE", "STRAVA_REFRESH_JOSE")
               if os.environ.get(k)), None)
    if not rt:
        sys.exit("no refresh token in the environment")
    tok = refresh_access_token(cid, csec, rt)["access_token"]

    meta = json.load(open(META_PATH))
    meta.setdefault("grades", {})
    fields = urllib.parse.urlencode({"keys": "latlng,distance,altitude", "key_by_type": "true"})

    failed = []
    for seg in meta["segments"]:
        sid = str(seg["id"])
        try:
            s = http(f"{API}/segments/{sid}/streams?{fields}", token=tok)
            alt = (s.get("altitude") or {}).get("data")
            dst = (s.get("distance") or {}).get("data")
            ll = (s.get("latlng") or {}).get("data")
            if not (alt and dst and ll) or not (len(alt) == len(dst) == len(ll)):
                raise ValueError("streams missing or ragged")
            poly, grades = resample(alt, dst, ll)
            if not poly:
                raise ValueError("zero length")
        except Exception as e:
            # Keep whatever line the file already had. A segment we cannot
            # refresh should lose its colour, not disappear off the map.
            failed.append(f"{sid} ({seg['name']}): {e}")
            print(f"[{sid}] FAILED, keeping the old line: {e}", flush=True)
            continue
        meta["polylines"][sid] = poly
        meta["grades"][sid] = grades
        print(f"[{sid}] {len(poly)} points, "
              f"{min(grades):+.1f}% to {max(grades):+.1f}%  {seg['name']}", flush=True)

    # Never leave a grades array that does not line up with its own polyline.
    for sid in list(meta["grades"]):
        if len(meta["grades"][sid]) != len(meta["polylines"].get(sid, [])):
            del meta["grades"][sid]
            print(f"[{sid}] dropped: grades did not match the line", flush=True)

    open(META_PATH, "w").write(dump(meta))
    print(f"\n{len(meta['grades'])}/{len(meta['segments'])} segments have grades. "
          f"{_rl['reads']} reads.")
    if failed:
        print("::warning::segments not refreshed: " + "; ".join(failed))


if __name__ == "__main__":
    main()
