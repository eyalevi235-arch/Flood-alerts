# arrival/ — זמן הגעה של גל שיטפון + מנוע התראות
Pipeline: forecast rain grid (Open-Meteo ICON/ECMWF, or PDIR/radar) -> flood probability (desert LightGBM model_pdir_radar_np + Platt + dry gate)
-> arrival (DEM time-area routing, SCS-CN per cell from gis/curve_number.tif) -> alerts JSON.
- travel_time.py  D8 catchment + per-cell velocity (channel VC=3.5 m/s at S=1%,A=100km2; hillslope 0.15 m/s) + travel time to point (cached cache/c_*.npz)
- calibrate.py    VC fit on Arugot 2:15h / Og 1.5h / Zin 2h (calib_pairs.json)
- routing.py      rain-weighted width-function routing; SCS-CN (lambda=0.05), event reset after 24h dry, intensity factor (0.3-3 mm/h); first wave = Q>=max(0.5 m3/s,3% peak)
- forecast.py     Open-Meteo live + historical-forecast (replay) adapter -> Grid; radar_grid() stub
- rain_sources.py PDIR scaled to mm (raw int16 = mm*100!)
- validate_events.py  event first-wave check (calib_events.csv)
- alert_engine.py live|replay DATE SRC ; subscriptions.json ; outputs alerts_*.json
Limitations: forecast/satellite rain miss most convective desert cells (Zin 25.11.2025: ICON 1.7 mm basin mean); Og pair under-predicted (0.7h vs 1.5h; 'upper' location unknown);
model probability floor without rain (handled by dry gate r24/5mm); confidence mostly 'low'; no radar feed.
