# Flood alerts ("שיטפון בדרך") — deploy spec for GitHub Pages + Actions

Target repo: https://github.com/eyalevi235-arch/Flood-alerts (public). Everything here is free: GitHub Pages, GitHub Actions, the Open-Meteo API (no key), and optionally a Google Apps Script web app.

## 1. Layout (push this bundle as-is to the repo root, branch `main`)
```
.github/workflows/hourly.yml   hourly cron + manual run: run the engine, then deploy site/ to Pages (actions/deploy-pages)
requirements.txt               numpy, pandas, requests, lightgbm, pywebpush (tested with numpy 2.5.4, pandas 3.1.0, lightgbm 4.7.0, pywebpush 2.5.0, Python 3.12-3.13)
engine/flood_engine.py         raster-free engine: Open-Meteo grid -> basin rain features -> LightGBM + Platt -> dry gate -> SCS-CN time-area routing -> ETA
engine/run_job.py              the hourly entry point; writes site/data/*.json and sends web push
data/catchments.json           precomputed per-point/per-basin tables on the fixed Open-Meteo 0.1° grid (29.4–33.4N, 34.2–36.0E):
                                 points{VPxx: area, elev, relief, model mask (cells, outlet weights, near-half), tt p10/median,
                                 routing groups (cell, CN bin, lag histogram in 10-min bins in km², area per travel-time band)}, basins{sid: mask+stats}
data/viewpoints.csv            38 flood viewing points (snapped outlets, access, safety, tt stats)
data/first_wave_times.csv      historical first-wave times (reports + validated FB posts)
data/basins_simplified.geojson desert/other station basins (simplified 0.004°), input for risk_live.geojson
data/basin_soil.csv            CN/soil per basin (reference; CN is already baked into catchments.json routing groups)
data/viewpoints.geojson        points as GeoJSON
model/desert_pdir_radar_np.txt LightGBM booster used by the alert engine (desert, non-perennial)
model/calibration.json         Platt a/b for that model
model/alert_calibration.json   ongoing threshold/DRY_MM tuning results (NOT yet applied; engine uses DRY_MM=5 like the box engine; override with env DRY_MM)
subscriptions/subscriptions.json  [] fallback subscription list (in-repo)
state/                         push_sent.json is created by the job (de-dup keys uid|point|eta-hour, 14-day retention) and committed by the workflow
site/                          static PWA (Hebrew RTL; map / points / alerts / settings). All URLs relative, so it works under /Flood-alerts/.
  index.html app.js sw.js manifest.json icons vendor/leaflet.*   (Leaflet served locally; tiles from tile.openstreetmap.org)
  data/streams.geojson basins.geojson risk_YYYY-MM-DD.geojson alerts_demo.json   static layers
  data/alerts_latest.json risk_live.geojson viewpoints.json config.json         written hourly by run_job.py (sample copies included)
tools/precompute_catchments.py how data/catchments.json was built (needs the DEM/CN rasters which stay off the repo; reference only)
tools/subscriptions_apps_script.gs  free subscription endpoint (see §4)
reference/                     original box code (FastAPI server, alert_engine, routing, travel_time, grid_features, live_risk) for reference only
vapid_public_key.txt           current VAPID PUBLIC key (safe to publish)
```

## 2. How the job runs
`python engine/run_job.py` (about 20 s on a laptop-class CPU; well under 5 min on a runner):
1. Fetch hourly precipitation for 741 grid points from `api.open-meteo.com/v1/forecast` (`models=icon_seamless`, `past_days=1`, `forecast_days=3`; falls back to `ecmwf_ifs025`).
2. For each of the 38 viewpoints, find the maximum calibrated probability over the next 72 h, apply the dry gate `p *= min(1, max(r24, routed rain)/DRY_MM)`, and route the rain from now−24 h to now+72 h. This gives the first wave, the peak, q_peak, the rain share by travel-time band and the top rain cells. → `site/data/alerts_latest.json` `{issued, source, stub, alerts:[...]}`. Alerts are threshold-free; per-user thresholds are applied in the browser and at push time.
3. For the 234 desert non-perennial basins, compute the maximum probability over 48 h (zeroed if r24 < DRY_MM) → `site/data/risk_live.geojson`.
4. `viewpoints.json` = viewpoints + historical first waves + current alert (replaces `/api/viewpoints`). `config.json` = `{vapid_public, risk_dates, live, subscribe_url}`.
5. Push: load subscriptions (SUBSCRIPTIONS_URL, else subscriptions/subscriptions.json). For each record whose favourite points or streams have `prob >= threshold`, send one web push per (user, point, ETA-hour).
6. The workflow commits `state/push_sent.json`, then uploads `site/` as the Pages artifact and deploys.

Engine parity: on an archived ICON wet case (13–15.3.2023) the outputs (probabilities, argmax time, routed rain, q_peak, first wave, contributions for VP02/VP11/VP14) were identical to the box `alert_engine.py`/`routing.py`. One small difference: the fallback ETA (rain-peak + travel-time percentiles, used when routing gives no runoff) is applied when p ≥ 0.05, not when p ≥ the user's threshold.

## 3. Setup steps for the cloud agent
1. Push the bundle to `main`. Settings → Pages → Source: **GitHub Actions**.
2. Repo secrets: `VAPID_PRIVATE_KEY` (a PEM string, or base64url DER; the owner provides it, it is NOT in the bundle) and `VAPID_PUBLIC_KEY` (the content of vapid_public_key.txt; it must match the private key). Optional: `SUBSCRIPTIONS_URL` and `SUBSCRIPTIONS_TOKEN`.
   - Repo variables (optional): `VAPID_SUB` (e.g. `mailto:owner@...`) and `SUBSCRIBE_URL` (the public POST URL the PWA uses; usually the same Apps Script URL without a token).
   - If the owner can't provide the existing private key, generate a new pair (`vapid --gen`, or with the cryptography package), store both as secrets, and replace vapid_public_key.txt. Existing browser subscriptions would then need to re-subscribe.
3. Run the workflow manually once (workflow_dispatch) and check `https://eyalevi235-arch.github.io/Flood-alerts/`.
4. Do not commit any `*.pem` or `.env` (they are already in .gitignore).

## 4. Subscriptions (static site, no backend): recommendation
The PWA keeps preferences (favourite points/streams, threshold) in `localStorage`. "הפעל התראות" creates a PushSubscription and builds the record `{uid, points, streams, threshold, push, updated}`. If `config.subscribe_url` is set, the record is POSTed there (`mode:no-cors`, text/plain) on every preference change. If it isn't set, the record is shown in a textarea for manual copy.

**Recommended (simplest, free, no card):** a Google Apps Script web app on a Google Sheet in the owner's Google account (`tools/subscriptions_apps_script.gs`).
- `doPost` upserts by uid.
- `doGet?token=` returns the JSON list. Store the URL+token as secrets `SUBSCRIPTIONS_URL` and `SUBSCRIPTIONS_TOKEN`, and the plain URL as variable `SUBSCRIBE_URL`. Push endpoints/keys stay private, not in the public repo.
- Alternatives:
  - (b) A Cloudflare Worker + KV on the free plan. It needs a Cloudflare account; no card is required.
  - (c) Manually paste records into `subscriptions/subscriptions.json`. This works for 1–2 users, but it publishes the push endpoints in a public repo, so it is acceptable only for the owner's own device.
  - A GitHub issue form is not recommended, because it requires every user to have a GitHub login and makes the subscriptions public.
- The "שלח בדיקה" button now shows a local notification only. A real server push can be tested by lowering the threshold to 0 for one favourite and running the workflow.

## 5. Known limitations
- Forecast input only: Open-Meteo ICON (ECMWF fallback) at 0.1°. The IMS radar live input requires an IMS token and a different grid (the precomputed tables are for the Open-Meteo grid). `USE_IMS_RADAR` exists but is ignored and off. PDIR/CHIRPS are training-only.
- GitHub cron is best-effort: runs can be delayed by 5–30 min, and scheduled workflows are disabled after 60 days without repo activity. The hourly state commit counts as activity.
- Model quality (desert test since 2023): ROC ≈ 0.77. The model was trained on PDIR satellite features and runs here on NWP forecast rain, so there is a domain shift. Thresholds and DRY_MM are still being tuned (model/alert_calibration.json). Treat the output as guidance, not an official warning.
- Viewpoint coordinates are partly estimated ("לאמת"). Some merged pairs were 5–25 km apart and still need checking.
- Web push on iPhone works only after "Add to Home Screen" (iOS 16.4+).
- Pages is public: all data files, including the viewpoints and first-wave CSVs with source references, are visible.
- Changing catchments, CN or travel-time parameters requires re-running tools/precompute_catchments.py on the machine that has the rasters.
