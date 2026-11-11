# מניפות סחף – מסירה לבוט האתר (תצוגה + שדות מנוע)
הבסיס: origin/main הנוכחי (כולל #39 שמוזג ו-#42). אין שינוי בגאומטריית המקטעים, במודל, ב-calibration.json, בספים או במערכי ההסתברות. מזהי v8p/v3e נשארים זהים.

PR #40 (הסרה מחוץ לגבול, טיוטה) נוגע ל-channel_segments.geojson, channel_extensions_desert.geojson, coverage.geojson, small_streams_de.geojson, app.js, tap.js, tap_basin.js, sw.js. **ה-PR הזה לא נוגע בקבצים האלה.** אם #40 ימוזג, מקטעים שהוסתרו פשוט לא יצוירו; מיפוי המניפה שלהם יישאר ב-fan_segments.json. חלק מהמניפות עלולות להיות בצד הירדני של הערבה – כדאי לסנן לפי השכבה שתוצג אחרי #40, או לפי review.

## קבצים חדשים
| קובץ | יעד | תפקיד |
|---|---|---|
| site/data/fans.geojson | שכבת תצוגה | פוליגוני מניפה. צבע לפי p של apex_seg (מ-segment_risk*.p). לחיצה: נוסח הדיסקליימר + טווח הגעה. |
| site/data/fan_crossings.geojson | שכבת מידע | נקודה אחת לכל כביש על כל מניפה. להציג כברירת מחדל רק כאשר display_default=true (כביש ממוספר, למשל 90). **לא התראה נפרדת.** |
| site/data/fan_segments.json | עזר סטטי | מיפוי id → fan_id, fan_pos, fan_apex_seg, kind (seg/ext). |
| data/fan_segments.json | קלט למנוע | אותו מיפוי. |
| site/data/segment_fans.json | ייכתב שעתי | דגל התפשטות אפשרית + טווח הגעה, מערכים לפי id. המנוע כותב אותו; לא לנקוט ב-p. |
| site/data/segment_fans_nondesert.json | ייכתב שעתי | אותו דבר לצפון/מרכז. |

### שדות חשובים ב-fans.geojson
fan_id, name_he, region, layer (desert/nondesert), known, method (standard/relaxed), confidence (high/medium/low), review (0/1), review_reasons, apex_seg, fan_len_km, footprint_km2, arrival_min_min, arrival_max_min (דקות, מעבר המניפה במהירות 0.5–2 מ׳/ש׳), possible_spreading, roads_crossing, credit.

**המלצת תצוגת ברירת מחדל:** מניפות desert עם confidence=high, או known=1. את השאר (צפון/מרכז ו-review=1, כולל פוליגונים גדולים בערבה) אפשר להציג בשכבת «בדיקה» או מאחורי מתג.

### segment_fans.json (אחרי הריצה השעתית)
מערכים באורך זהה ל-segment_risk.p: spread (0/1), fan_id, fan_pos (0 בראש, 1 בבוהן), apex, rel_lo/rel_hi (דקות יחסיות ליתרת האורך), eta_lo/eta_hi (דקות מהרגע אם יש em לראש), flag_he="התפשטות אפשרית". רשימת extensions בנפרד (אין להן תא ב-p).

## שינויי קוד מומלצים באתר (לא ב-PR הזה, כדי לא להתנגש עם #40)
1. **app.js:** לטעון data/fans.geojson כשכבה מתחת לקווי הערוץ, מקווקו/שקוף, צבע לפי p[apex_seg] (או אפור אם אין). לטעון data/fan_crossings.geojson; לסנן display_default. סמל מידע (לא ⚠ התראה).
2. **קווי ערוץ על המניפה:** אופציונלי – dashArray ל-id שמופיע ב-fan_segments (kind=seg או ext).
3. **tap.js / בועת מידע:** אם הנקודה בתוך פוליגון מניפה, להציג את נוסח הדיסקליימר (אחרי אישור איל), את הדגל «התפשטות אפשרית», ואת טווח ההגעה. אם יש segment_fans.eta_lo/hi למקטע – להשתמש בהם; אחרת arrival_min_min/max_min של המניפה מעל ה-ETA של הראש.
4. **אין שינוי בלוגיקת ה-push, בסף או ב-p.**
5. **sw.js:** להעלות את גרסת המטמון (C) אחרי ש-#40 יוכרע, כדי לא לדרוך על flood-v41.
6. **ייחוס:** להוסיף את שורת Copernicus + OSM שב-DISCLAIMER_DRAFT.md.

## הסתברות
ההסתברות על המניפה (פוליגון, והארכות תצוגה) = p של מקטע הראש (apex_seg / src_seg). מערכי p במקטעי המודל לא משתנים (בדיקת זהות עברה, כולל מקרה סינתטי שבו p שונה בין מקטע לראש).

## בדיקות
- tools/test_fans_prob_identity.py <repo>: IDENTITY_OK.
- צילומים: docs/alluvial_fans/*.png (ארצי, ים המלח, ערבה, 13 ידועות, צפון/מרכז).
