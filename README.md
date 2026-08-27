# tourdesocal.com

Are you stronger than 2024 Michael? A self-updating cycling standings site for four
friends, live at <https://tourdesocal.com>.

**If you are picking this project up cold, read [HANDOFF.md](HANDOFF.md) first.** It is
the authoritative description of how the project actually works. This file covers the
overview and the remaining setup.

## The name is a joke, Michael is not frozen

"2024 Michael" is branding, nothing more. Michael is a live, auto-updating rider
exactly like the other three, and he needs to authorize Strava exactly like the other
three. The old `michael_frozen` block in `state.json` and its special-case logic in
`update.py` were removed on 2026-08-24. Do not reintroduce them.

## Riders

| Rider   | Weight (lb) |
| ------- | ----------- |
| Ali     | 183         |
| Michael | 175         |
| Randee  | 187         |
| Jake    | 190         |

Weights feed the W/kg display only. Ask Ali before changing them.

## Scoring

Twenty one tracked segments, scored like a Tour de France General Classification.

- **GC**: total elapsed time across all 21 segments. Lowest total wins the yellow jersey.
- **Segment not attempted**: you are assessed the slowest finisher's time on that
  segment plus 10 percent (`PENALTY = 1.10` in `index.html`). The multiplier is
  deliberate so the penalty scales with segment length.
- **KOM crown**: fastest rider on a segment.
- **GOT BONED**: last place on a segment. Applies to whoever is slowest, not just Michael.

## What counts as a ride

E-bike rides and Peloton rides do not count for anything. Not segment times, not
power, not KOMs. `update.py` skips the whole activity. This is deliberate: an
e-bike will demolish a segment, and a Peloton has no business on a GC.

Zwift and other smart trainer rides arrive as `VirtualRide` with `device_watts`
and do count, indoors or out.

## Power rules

Cards show W/kg at 5, 10, 20, 30 and 60 minutes.

Only real power meter data is ever published. Never Strava's estimates.

- Requires `device_watts` on the activity.
- E-bike and Peloton already excluded upstream, per the section above.
- Zwift and outdoor rides are fine as long as a power meter was recording.

Baseline numbers in `OFFICIAL_W` came from the riders' own Strava best-efforts pages
and are authoritative. `update.py` only overwrites a value when the new one beats it.
If a power curve looks physiologically impossible, it is. Flag it, do not publish it.

## Architecture

Static site. No build step, no framework, no bundler.

```
index.html                    markup, CSS and all client-side logic
auth.html                     Strava authorization landing page for riders
data.js                       generated. window.SITE_DATA = {updated, segs, power}
avatars.js                    small circular avatars for the segment tables
photos-*.js                   one per rider, full card photo as a base64 WebP data URI
data/state.json               source of truth. Rolling PRs, attempt counts, power bests
data/meta.json                segment metadata and map polylines
scripts/update.py             the daily updater
scripts/exchange_token.py     OAuth code to refresh token helper, fallback only
.github/workflows/update.yml  cron
.github/workflows/exchange-token.yml  code to refresh token, no secret handling
CNAME                         tourdesocal.com
```

Maps are Leaflet 1.9.4 from unpkg with CARTO `light_all` tiles.

**Do not hand-edit `data.js`.** The Action regenerates and force-commits it. Edit
`data/state.json` or `update.py` instead.

Polyline keys in `data/meta.json` must stay sorted numerically. If you regenerate from
Python, sort with `key=int` or the file churns on every run.

## How updates work

`.github/workflows/update.yml` runs `scripts/update.py` on cron `0 15 * * *`, which is
08:00 PDT and 07:00 PST in winter. It can also be run by hand from Actions, Update
standings, Run workflow.

This is a daily batch job, not a webhook. Rides do not appear the moment they are
uploaded. For each rider holding a refresh token the script:

1. Lists activities since `last_epoch` minus a 3 day overlap, to catch late uploads.
2. Fetches each activity with `include_all_efforts=true` and scans efforts against the
   14 tracked segment IDs, updating PRs and attempt counts.
3. Pulls `time` and `watts` streams and computes best rolling averages at
   300, 600, 1200, 1800 and 3600 seconds, subject to the power rules above.
4. Rewrites `data/state.json` and `data.js`, and commits if anything changed.

It sleeps 1 second per activity to stay inside Strava's rate limits.

A rider with no refresh token is skipped with a log line, not an error. Their existing
baseline times keep serving, so a missing token degrades gracefully. The side effect is
that an unauthorized rider currently looks identical to a frozen one.

Attempt counts only accumulate where a baseline count already exists, currently Ali
only. Everyone else shows a dash. A full history backfill is possible but not written.

## Remaining setup

Done already: repo, GitHub Pages, custom domain, HTTPS, Actions write permissions, the
Strava API application, and `STRAVA_CLIENT_ID`.

What is left: `STRAVA_CLIENT_SECRET`, `ACTIONS_PAT`, and the four refresh tokens.
Verified against the repo settings on 2026-08-25: `STRAVA_CLIENT_ID` is the only
secret that actually exists. Do not trust a doc that says otherwise, check the
Settings page.

### 1. Raise the connected athlete cap first

New Strava API applications are capped at **one connected athlete**. The second rider
to authorize gets `Error 403: Limit of connected athletes exceeded`, and their
authorization code is burnt. Codes are single use.

Click **Upgrade** at <https://www.strava.com/settings/api> before sending anyone the
link. That raises the cap to 10 athletes and lifts the rate limits. Strava only
requires a formal app review above 10 athletes, so four riders is fine.

### 2. Confirm the Strava callback domain

Authorization Callback Domain must be `tourdesocal.com` for `auth.html` to work.

### 3. Send riders the link

Send each rider <https://tourdesocal.com/auth.html>. They tap Authorize, leave all
permission boxes ticked, land back on the page, and send Ali the code it displays. The
page warns them if a permission box was unticked and shows a countdown so they send it
promptly.

Codes die within minutes, so do the riders one at a time and only when you are at a
computer with the Actions tab already open. A code that sits in a text thread while you
find your laptop is a dead code.

### 4. Exchange each code for a refresh token

Actions, Exchange Strava code, Run workflow. Pick the rider, paste the code, run it. The
workflow trades the code against the stored client secret, masks the token, and writes
`STRAVA_REFRESH_<RIDER>` for you. Nobody has to see the secret or the token.

It needs `ACTIONS_PAT` to exist first, because `GITHUB_TOKEN` cannot write secrets. That
is a fine-grained personal access token scoped to this repo only, with Secrets read and
write.

One tradeoff to know: this repo is public, so the pasted code appears in the run metadata
for anyone who looks. The code is consumed and dead by the time the run finishes, so this
is noise rather than exposure, but it is the reason the token itself never appears.

`scripts/exchange_token.py` does the same job from a laptop and is kept as a fallback,
but it means handling the client secret by hand. Prefer the workflow.

Refresh tokens are long lived, so this is once per rider.

### 5. Secrets

Settings, Secrets and variables, Actions.

| Secret                   | Status       |
| ------------------------ | ------------ |
| `STRAVA_CLIENT_ID`       | set (274192) |
| `STRAVA_CLIENT_SECRET`   | pending      |
| `ACTIONS_PAT`            | pending      |
| `STRAVA_REFRESH_ALI`     | pending      |
| `STRAVA_REFRESH_JAKE`    | pending      |
| `STRAVA_REFRESH_RANDEE`  | pending      |
| `STRAVA_REFRESH_MICHAEL` | pending      |

### 6. Test

Actions, Update standings, Run workflow. A green check means it worked, and the
"Last updated" date in the site footer confirms it end to end.

## Credential handling

Never handle the client secret or another rider's refresh token on their behalf.
Authorization codes are single use and expire within minutes, so a code sitting in a
chat log is almost certainly already dead.

## House rules

- Keep the tone. This is a trash-talk site, not a diplomatic one.
- No em dashes in site copy.
- Binary uploads are not available in this setup, which is why rider photos live as
  base64 data URIs inside `photos-*.js` rather than as image files.
