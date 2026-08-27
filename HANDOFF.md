# HANDOFF

Context for anyone (human or AI) picking this project up cold. Read this before
touching anything. `README.md` covers first-time setup; this file covers what the
project actually is now and what is still unfinished.

Owner: Ali (ali@skyline-cp.com). Live at https://tourdesocal.com

## What this is

A joke trash-talk cycling site for four friends. It compares their Strava times on
14 tracked segments and scores them like the Tour de France General Classification.
It is meant to be funny, not diplomatic. Keep the tone.

## Naming gotcha, read this first

The site is called "2024 Michael" and the headline asks "Are you stronger than 2024
Michael?". **That branding is a gimmick and nothing more.** Michael is a fully live,
auto-updating rider exactly like the other three. His times are not frozen. There
used to be a `michael_frozen` block in `state.json` and special-case logic in
`update.py`; both were removed on 2026-08-24. Do not reintroduce them.

Any doc or comment claiming Michael is a frozen benchmark is stale.

## Riders

| Rider | Weight (lb) | Notes |
|---|---|---|
| Ali | 183 | repo owner |
| Michael | 175 | the "2024 Michael" of the title |
| Randee | 187 | |
| Jake | 190 | |

Weights are used only for the W/kg power display. Ali set them; ask before changing.

## Scoring rules

- **General Classification**: total elapsed time across all 14 segments. Lowest total
  wins. Yellow jersey to first place.
- **Did not attempt a segment**: you are assessed the slowest finisher's time on that
  segment **plus 10%** (`PENALTY = 1.10` in `index.html`). Ali picked 10% over a flat
  60s deliberately, so it scales with segment length.
- **GOT BONED**: whoever is last place on a given segment gets the badge. It reads
  "MIKE GOT BONED" for Michael and "<NAME> GOT BONED" for everyone else. This is not
  Michael-specific, it applies to whoever is slowest.
- **KOM crown**: fastest rider on a segment. Cards show a running KOM count next to
  the boned count.

## Power numbers, important

The cards show W/kg for 5 / 10 / 20 / 30 / 60 minutes.

Hard rule from Ali: **only real power meter data. Never Strava's estimates.**

- Requires `device_watts` true on the activity.
- Zwift and regular outdoor rides are fine as long as there is a power meter.

**Separate and broader hard rule, added 2026-08-25: e-bike and Peloton rides do
not count for ANYTHING.** Not power, not segment times, not KOMs. `update.py`
skips the entire activity after fetching it. This closes a hole where an e-bike
ride could not pollute a W/kg number but could still set a segment PR and take a
crown. Zwift is explicitly fine.

The current baseline numbers in `OFFICIAL_W` in `index.html` were supplied by the
riders themselves from their Strava best-efforts pages. They are authoritative.
`update.py` computes new bests from activity streams and only overwrites a value if
it beats the existing one.

Historical warning: an earlier scrape produced a physiologically impossible curve for
Michael (413/374/364/353/228, a 35% cliff between 30min and 60min). It came from five
junk activities. If a power curve looks impossible, it is. Do not publish it, flag it.

## Architecture

Static site, no build step, no framework, no bundler.

```
index.html         everything: markup, CSS, all client-side logic
data.js            generated. window.SITE_DATA = {updated, segs, power}
avatars.js         small circular avatars used in the segment tables
photos-*.js        one per rider. Full card photo as a base64 WebP data URI
data/state.json    source of truth. Rolling PRs, attempt counts, power bests
data/meta.json     segment metadata + map polylines
scripts/update.py  the daily updater
scripts/exchange_token.py   OAuth code -> refresh token helper
.github/workflows/update.yml   cron
CNAME              tourdesocal.com
```

Leaflet 1.9.4 from unpkg for the maps, CARTO `light_all` tiles. Theme is white and
deliberately Strava-like.

**Do not hand-edit `data.js`.** The Action regenerates and force-commits it. Edit
`data/state.json` or `update.py` instead.

`data/meta.json` polyline keys must stay sorted numerically. JS `JSON.stringify`
orders numeric-like keys ascending; if you regenerate from Python, sort with
`key=int` or the file churns on every run.

## The daily updater

`.github/workflows/update.yml`, cron `0 15 * * *` = 08:00 PDT (07:00 PST in winter).
Also runnable manually via Actions -> Update standings -> Run workflow.

Per rider with a refresh token it:
1. Lists activities since `last_epoch` minus a 3 day overlap, to catch late uploads.
2. Pulls each activity with `include_all_efforts=true`, scans segment efforts against
   the 14 tracked IDs, updates PRs and attempt counts.
3. Pulls `time` and `watts` streams and computes best rolling averages for
   300/600/1200/1800/3600s, subject to the power rules above.
4. Rewrites `data/state.json` and `data.js`, commits if anything changed.

It sleeps 1s per activity to stay inside Strava's rate limits.

## Secrets

Repo Settings -> Secrets and variables -> Actions. Values are never stored here.
Status column verified against the live settings page on 2026-08-25. An earlier
version of this table wrongly claimed the client secret was set. Check the page,
do not trust the table.

| Secret | Status |
|---|---|
| `STRAVA_CLIENT_ID` | set (274192) |
| `STRAVA_CLIENT_SECRET` | **pending** |
| `ACTIONS_PAT` | **pending** |
| `STRAVA_REFRESH_ALI` | **pending** |
| `STRAVA_REFRESH_JAKE` | **pending** |
| `STRAVA_REFRESH_RANDEE` | **pending** |
| `STRAVA_REFRESH_MICHAEL` | **pending** |

A rider with no token is skipped with a log line, not an error. The site keeps
serving their existing baseline times, so a missing token degrades gracefully.

`ACTIONS_PAT` is a fine-grained personal access token scoped to this repo only, with
Secrets read and write. `.github/workflows/exchange-token.yml` needs it because
`GITHUB_TOKEN` cannot write secrets. It is the one credential step nobody can take off
Ali, since delegating it would mean the token passing through whoever is helping.

**Never handle the client secret or refresh tokens on a rider's behalf.** The refresh
tokens are produced by the Exchange Strava code workflow, which trades the code against
the stored client secret inside Actions and writes `STRAVA_REFRESH_<RIDER>` directly.
Nobody sees either value. `scripts/exchange_token.py` does the same job from a laptop
and is kept as a fallback, but it means handling the client secret by hand, so prefer
the workflow.

Authorization codes are single use and expire in minutes, so a code pasted into a chat
is almost certainly already dead. The relay is the weak point of this whole flow: the
rider has to send the code and Ali has to run the workflow inside the same few minutes.
Do riders one at a time, with the Actions tab already open, rather than sending all four
the link at once.

## Strava API gotcha: Single Player Mode

New Strava API apps are capped at **1 connected athlete**. The second rider to
authorize gets `Error 403: Limit of connected athletes exceeded`. The fix is the
self-service **Upgrade** button at https://www.strava.com/settings/api which raises
the cap to 10 athletes (and to 200/2000 read, 400/4000 overall rate limits). Only
above 10 athletes does Strava require a formal app review. Four riders fits fine.

## Current standings snapshot (2026-08-24, 14 segments)

| | Rider | Total | Gap | KOMs | Boned |
|---|---|---|---|---|---|
| 1 | Randee | 3:18:50 | yellow jersey | 6 | 3 |
| 2 | Ali | 3:21:35 | +2:45 | 3 | 3 |
| 3 | Michael | 3:30:36 | +11:46 | 3 | 5 |
| 4 | Jake | 3:36:15 | +17:25 | 2 | 3 |

These will move once the tokens land and the Action starts running for real.

## Status

Done:
- Site live on GitHub Pages, custom domain, HTTPS enforced.
- White Strava-style theme, responsive segment tables, Leaflet maps.
- TdF time-based GC with the +10% DNS penalty.
- KOM crowns and boned counts.
- W/kg power rows from rider-supplied official numbers.
- Michael converted to a live auto-updating rider (2026-08-24).
- All four card photos letterboxed so the full picture fits the card
  (`object-fit: contain`, `aspect-ratio: 480/340`).
- Irvine Boyz logo as favicon.
- `auth.html`, the rider-facing Strava authorization page.
- `README.md` rewritten for 14 segments, live Michael, and the workflow token flow.
- `.github/workflows/exchange-token.yml`, so no one handles the client secret.

Pending:
- `ACTIONS_PAT`. The exchange workflow fails without it.
- All four refresh tokens. Nothing auto-updates until at least one lands.
- Confirm the capacity upgrade is applied before asking riders to authorize.
- Attempt counts only accumulate where a baseline exists (Ali only). Others show a
  dash. A full-history backfill is possible but not written.
- Rider photos to be replaced. Base64 WebP data URIs in `photos-*.js`, since binary
  uploads are not available in this setup.

## Working notes

- Ali does not do manual steps. Automate or do it for him, but never with his
  credentials.
- No em dashes in site copy. He asked for this explicitly.
- Binary uploads into the repo are not available in this setup, which is why photos
  live as base64 data URIs inside `photos-*.js` rather than as image files.
