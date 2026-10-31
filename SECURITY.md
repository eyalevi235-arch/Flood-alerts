# אבטחה — שיטפון בדרך

האתר ציבורי. הוא כלי עזר ניסיוני, לא מערכת התרעה רשמית. הדיווח על בעיה אבטחה לא צריך לכלול מפתח פרטי, כתובת Push, או תוכן של גיליון ההרשמות.

אם יש חשבון GitHub: Settings → Code security → Private vulnerability reporting. אפשר גם לפתוח דיווח פרטי לבעל המאגר. לא לפרסם סוד ב-Issue ציבורי.

## מה כבר מוגדר בקוד

- הרשמות נשמרות רק ב-Google Sheet פרטי. הקובץ `subscriptions/*.json` לא נקרא על ידי העבודה השעתית ולא נשמר בגיט.
- `doGet` מחזיר את הרשימה רק עם `TOKEN`. בלי הטוקן חוזרת רשימה ריקה.
- פוסט ציבורי יכול רק לרשום או למחוק את אותה כתובת Push. אין פעולה ששולחת התראה.
- כתובת Push חייבת להיות `https` על `fcm.googleapis.com`, `updates.push.services.mozilla.com`, `*.push.apple.com` או `*.notify.windows.com`. שדות אחרים נזרקים. יש תקרת גודל, תקרת שורות, והגבלה לפי כתובת ולפי שעה (`CacheService`).
- שליחה קורית רק ב-GitHub Action כש-`VAPID_PRIVATE_KEY` מוגדר. הטקסט נבנה משדות התחזית שלנו. כתובת שמחזירה 404 או 410 נמחקת מהגיליון.
- באתר אין סקריפטים מצד שלישי ואין CDN, אז אין SRI. עיצוב ומפה מקומיים. אריחי המפה מ-OpenStreetMap.
- Content-Security-Policy ב-meta: `script-src 'self'`. `style-src` כולל `'unsafe-inline'` כי Leaflet כותב סגנון על המפה עצמה. תג meta לא יכול לקבוע `frame-ancestors`; GitHub Pages לא נותן כותרות HTTP משלנו.
- `Referrer-Policy: no-referrer`.
- טקסט שמגיע מהנתונים נכנס לעמוד דרך `textContent`, לא דרך `innerHTML`.
- ה-workflow מצמיד Actions ל-SHA, נועל את חבילות Python עם hash, ומפצל הרשאות: עבודת החישוב `contents: write`, עבודת הפרסום `pages: write` ו-`id-token: write`.
- Dependabot מוגדר ל-`github-actions` ול-`pip` (קובץ `.github/dependabot.yml`).
- סריקת סודות (secret scanning) פועלת במאגרי ציבור ב-GitHub.

## מה הבעלים צריך לעשות ידנית

1. להפעיל אימות דו-שלבי (2FA) על חשבון GitHub, וגם על חשבון Google שמחזיק את הגיליון.
2. להגן על הענף `main`: Settings → Rules → Rulesets. מומלץ לחסום force-push ומחיקת הענף, ולבקש Pull Request לפני מיזוג. העבודה השעתית דוחפת את `state/push_sent.json` עם `GITHUB_TOKEN`. צריך לאפשר ל-GitHub Actions לעקוף את כלל ה-PR (bypass), אחרת שמירת מצב השליחה תיכשל. הפרסום לאתר עדיין ימשיך.
3. לאשר ש-secret scanning דולק. אם יש מתג Push protection תחת Settings → Code security and analysis, להפעיל אותו.
4. להפעיל Dependabot security updates באותו מסך (קובץ Dependabot מכסה עדכוני גרסה; עדכוני אבטחה הם מתג נפרד).
5. להפעיל Private vulnerability reporting.
6. להדביק מחדש את `tools/subscriptions_apps_script.gs` ב-Apps Script ולפרוס deployment חדש. אם בגיליון הישן עמודה A הייתה מזהה משתמש, למחוק את השורות הישנות. המפתח עכשיו הוא כתובת ה-Push.
7. לא לשים במאגר מפתח פרטי, קובץ PEM, או רשומת התראה. `SUBSCRIBE_URL` חייב להיות כתובת `https://script.google.com/...` בלבד.
8. אם Pages עוד לא הוגדר: Settings → Pages → Source → GitHub Actions, ואז Run workflow.
9. לעבור על Pull Requests של Dependabot לפני מיזוג.

## מגבלות

- האתר והנתונים ציבוריים. מיקום נקודות התצפית גלוי.
- בלי כותרות HTTP אי אפשר לנעול `frame-ancestors`. ה-CSP יושב בתג meta.
- Leaflet דורש `'unsafe-inline'` לסגנון. אין `'unsafe-inline'` לסקריפטים.
- הטוקן של הגיליון נשלח כפרמטר `token` ב-GET של העבודה השעתית. הוא צריך להיות ארוך (לפחות 16 תווים, עדיף 32), והוא לא נכתב ללוג שלנו.
