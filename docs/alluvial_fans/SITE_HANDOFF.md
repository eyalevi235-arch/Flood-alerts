# מניפות סחף – מסירה לבוט האתר (תצוגה + שדות מנוע)
הבסיס: origin/main (047bda7, כולל #39, #41, #42). **אין לשלב (merge) את #44 מכאן** — בוט האתר ממזג את #40, #43 ו-#44. אין שינוי בגאומטריית המקטעים, במודל, ב-calibration.json, בספים או במערכי ההסתברות. מזהי v8p/v3e נשארים זהים.

PR #40 (הסרה מחוץ לגבול, פתוח) ו-#43 (קרדיט שמ״ט, פתוח) נוגעים ל-channel_segments*.geojson, coverage.geojson, small_streams_de.geojson, app.js, tap.js, tap_basin.js, sw.js, index.html. **ה-PR הזה (#44) לא נוגע בקבצים האלה.** סדר מיזוג מוצע: קודם #40 (גאומטריית תצוגה + sw flood-v41), אחר כך #43 (קרדיט + sw flood-v42; יישב את קונפליקט sw.js מול #40), ואז #44 (קבצים חדשים בלבד; להעלות את גרסת המטמון C אחרי המיזוג). אם #40 ימוזג לפני #44, מקטעים שהוסתרו פשוט לא יצוירו; מיפוי המניפה של מקטע שהוסר יישאר ב-fan_segments.json אבל לא יוצג.

## קבצים חדשים — שכבה מפורסמת בלבד
78 מניפות שסומנו `review` **מוסתרות** עד לסקירה: הן לא ב-`site/data/` ולא נטענות במנוע. הארכיון הפנימי: `data/alluvial_fans_review/` (האתר לא טוען את התיקייה הזו).

| קובץ | יעד | תפקיד |
|---|---|---|
| site/data/fans.geojson | שכבת תצוגה | 108 פוליגוני מניפה במדבר (כולל 13 ידועות). צבע לפי p של apex_seg (מ-segment_risk*.p). |
| site/data/fan_crossings.geojson | שכבת מידע | נקודה אחת לכל כביש על כל מניפה מפורסמת. להציג כברירת מחדל רק כאשר display_default=true (כביש ממוספר, למשל 90). **לא התראה נפרדת.** |
| site/data/fan_segments.json | עזר סטטי | מיפוי id → fan_id, fan_pos, fan_apex_seg, kind (seg/ext), רק לשכבה המפורסמת. |
| data/fan_segments.json | קלט למנוע | אותו מיפוי מפורסם. |
| site/data/segment_fans.json | ייכתב שעתי | דגל התפשטות אפשרית + טווח הגעה, מערכים לפי id. המנוע כותב אותו; לא לשנות את p. |
| site/data/segment_fans_nondesert.json | ייכתב שעתי | כרגע ריק למעשה (כל מניפות צפון/מרכז מוסתרות עד לסקירה). |

### שדות ב-fans.geojson
fan_id, name_he, region, layer=desert, known, method, confidence, apex_seg, fan_len_km, footprint_km2, arrival_min_min, arrival_max_min (דקות, מעבר המניפה במהירות 0.5–2 מ׳/ש׳), possible_spreading, roads_crossing, credit. בשכבה המפורסמת אין מניפות עם review=1.

### נוסח בועת המידע (מאושר, להציג כלשונו)
מניפת סחף – הזרימה עלולה להתפזר ולשנות אפיק; זמן הגעה משוער X–Y דק׳. ההסתברות המוצגת היא ההסתברות בראש המניפה. הפוליגון הוא הערכה ואינו גבול בטוח.

להחליף את X–Y בטווח הדקות (eta_lo–eta_hi אם קיים למקטע, אחרת arrival_min_min–arrival_max_min של המניפה).

### segment_fans.json (אחרי הריצה השעתית)
מערכים באורך זהה ל-segment_risk.p: spread (0/1), fan_id, fan_pos (0 בראש, 1 בבוהן), apex, rel_lo/rel_hi, eta_lo/eta_hi, flag_he="התפשטות אפשרית". רשימת extensions בנפרד.

## שינויי קוד מומלצים באתר (לא ב-PR הזה, כדי לא להתנגש עם #40 ו-#43)
1. **app.js:** לטעון data/fans.geojson כשכבה מתחת לקווי הערוץ, מקווקו/שקוף, צבע לפי p[apex_seg] (או אפור אם אין). לטעון data/fan_crossings.geojson; לסנן display_default. סמל מידע (לא התראה). **לא לטעון** את data/alluvial_fans_review/.
2. **קווי ערוץ על המניפה:** אופציונלי – dashArray ל-id שמופיע ב-fan_segments (kind=seg או ext).
3. **tap.js / בועת מידע:** אם הנקודה בתוך פוליגון מניפה, להציג את נוסח הבועה המאושר כלשונו, את הדגל «התפשטות אפשרית», ואת טווח ההגעה במקום X–Y.
4. **אין שינוי בלוגיקת ה-push, בסף או ב-p.**
5. **sw.js:** להעלות את גרסת המטמון (C) אחרי מיזוג #40 ו-#43, כדי לא לדרוך על flood-v41/v42.
6. **ייחוס:** שורת Copernicus + OSM שב-DISCLAIMER_DRAFT.md.

## הסתברות
ההסתברות על המניפה (פוליגון, והארכות תצוגה) = p של מקטע הראש (apex_seg / src_seg). מערכי p במקטעי המודל לא משתנים.

## בדיקות
- tools/test_fans_prob_identity.py <repo>
- tools/check_json_strict.py
- צילומים: docs/alluvial_fans/*.png (השכבה המפורסמת בלבד; מניפות צפון/מרכז אינן מוצגות).
