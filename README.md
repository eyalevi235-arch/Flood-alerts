# שיטפון בדרך

אתר בעברית, מימין לשמאל, שמראה איפה יש סיכוי לשיטפון במדבר. אפשר לפתוח אותו בטלפון ולהוסיף למסך הבית.

הכתובת:

https://eyalevi235-arch.github.io/Flood-alerts/

הכול בחינם, בלי כרטיס אשראי: GitHub Pages לאתר, GitHub Actions לבדיקה השעתית, ותחזית גשם מ-Open-Meteo (בלי מפתח).

## מה קורה כל שעה

בדקה ה-7 של כל שעה (לפי שעון UTC) רצה בדיקה אוטומטית בשם `hourly-forecast`:

1. מורידים תחזית גשם מ-Open-Meteo.
2. מחשבים סיכוי ל-38 נקודות תצפית ולנחלים.
3. שומרים את `site/data/alerts_latest.json` ואת `site/data/risk_live.geojson` ומפרסמים את תיקיית `site/` לאתר.
4. אם הוגדרו התראות, נשלחת התראה לטלפון. אם עוד לא הגדרתם, השלב הזה פשוט מדולג והאתר מתעדכן כרגיל.

אפשר גם להריץ ידנית: [Actions → hourly-forecast → Run workflow](https://github.com/eyalevi235-arch/Flood-alerts/actions/workflows/hourly.yml).

## להדליק את האתר (פעם אחת)

אם העמוד עדיין לא נפתח, צריך לבחור את מקור הפרסום. זה כפתור אחד:

1. פתחו [Settings → Pages](https://github.com/eyalevi235-arch/Flood-alerts/settings/pages).
2. תחת **Build and deployment**, בשדה **Source**, בחרו **GitHub Actions**.
3. אין צורך בענף `gh-pages` ואין צורך בדומיין משלכם.

אחר כך הריצו פעם אחת את [hourly-forecast](https://github.com/eyalevi235-arch/Flood-alerts/actions/workflows/hourly.yml) עם **Run workflow**. אחרי כמה דקות האתר אמור לעלות.

אם הריצה נעצרת עם הודעה על הרשאות (`Resource not accessible by integration` או `pages: write`):

1. פתחו [Settings → Actions → General](https://github.com/eyalevi235-arch/Flood-alerts/settings/actions).
2. גללו אל **Workflow permissions**.
3. בחרו **Read and write permissions** ושמרו.
4. הריצו שוב את `hourly-forecast`.

## מפתחות להתראות (VAPID)

האתר עובד גם בלי המפתחות. בליהם אי אפשר לשלוח התראה מהבדיקה השעתית אל הטלפון.

המפתח הפרטי לא נמצא בחבילה, ולא ניתן היה לשמור אותו כ-Secret מההתקנה הזו. צרו זוג חדש אצלכם, והדביקו אותו ב-GitHub. אל תעלו את המפתח הפרטי לגיט, ואל תשלחו אותו בצ'אט.

הקובץ `vapid_public_key.txt` שכבר במאגר הוא מפתח ציבורי מהחבילה המקורית. אחרי שתיצרו זוג חדש, החליפו את השורה שבקובץ.

1. במחשב, בתיקייה זמנית **מחוץ** למאגר:

```bash
mkdir -p /tmp/flood-vapid && cd /tmp/flood-vapid
python3 -m venv .venv
.venv/bin/pip install pywebpush
.venv/bin/vapid --gen --applicationServerKey
```

2. על המסך תופיע שורה אחת: `Application Server Key = ...`. זו המפתח הציבורי. העתיקו רק את המפתח (בלי הרווח שאחרי הסימן `=`).
3. פתחו את `vapid_public_key.txt` במאגר, מחקו את השורה הישנה, והדביקו את המפתח החדש. שמרו, עשו commit ו-push.
4. פתחו [Settings → Secrets and variables → Actions](https://github.com/eyalevi235-arch/Flood-alerts/settings/secrets/actions).
5. **New repository secret**
   - שם: `VAPID_PRIVATE_KEY`
   - ערך: כל התוכן של הקובץ `/tmp/flood-vapid/private_key.pem`, כולל השורות `BEGIN` ו-`END`.
6. **New repository secret** נוסף
   - שם: `VAPID_PUBLIC_KEY`
   - ערך: אותה שורה ציבורית ששמתם ב-`vapid_public_key.txt`.
7. מחקו את הקבצים מהמחשב:

```bash
rm -f /tmp/flood-vapid/private_key.pem /tmp/flood-vapid/public_key.pem
```

8. אופציונלי, בלשונית **Variables** (לא Secrets): שם `VAPID_SUB`, ערך `mailto:you@example.com`.
9. הריצו שוב את `hourly-forecast`. הבדיקה תכתוב את המפתח הציבורי אל `site/data/config.json` של האתר.

מי שכבר נרשם להתראות לפני החלפת המפתח צריך ללחוץ שוב על «הפעל התראות».

## הרשמות להתראות (מומלץ, חינם)

ההעדפות (נקודות, נחלים, סף) נשמרות בטלפון עצמו. כדי שהבדיקה השעתית תדע למי לשלוח, צריך מקום אחד ששומר את ההרשמה. הדרך החינמית המומלצת: Google Sheet ו-Apps Script בחשבון Google שלכם.

עד שזה מוגדר, האתר והבדיקה השעתית רצים כרגיל. מי שמפעיל התראות רואה תיבת טקסט עם הרשומה, ואפשר להעתיק אותה ידנית.

### הקמה

1. צרו Google Sheet חדש, למשל בשם `flood-subscriptions`. השאירו את הגיליון ריק.
2. בתפריט: **Extensions → Apps Script**.
3. מחקו את מה שמופיע שם, והדביקו את כל הקובץ [`tools/subscriptions_apps_script.gs`](tools/subscriptions_apps_script.gs). שמרו.
4. לחצו על גלגל השיניים (**Project Settings**). תחת **Script properties** לחצו **Add script property**.
   - Property: `TOKEN`
   - Value: סיסמה ארוכה שאתם ממציאים (כ-32 תווים). שמרו.
5. למעלה: **Deploy → New deployment**.
   - ליד **Select type** בחרו **Web app**.
   - Execute as: **Me**.
   - Who has access: **Anyone**.
   - **Deploy**, ואשרו את ההרשאות לחשבון Google.
6. העתיקו את כתובת ה-Web app. היא נגמרת ב-`/exec`.

### לחבר את הכתובת ל-GitHub

ב-[Secrets and variables → Actions](https://github.com/eyalevi235-arch/Flood-alerts/settings/secrets/actions):

| מקום | שם | מה שמים |
| --- | --- | --- |
| Secret | `SUBSCRIPTIONS_URL` | כתובת ה-Web app |
| Secret | `SUBSCRIPTIONS_TOKEN` | אותו `TOKEN` משלב 4 |
| Variable | `SUBSCRIBE_URL` | אותה כתובת Web app, בלי הטוקן |

הריצו את `hourly-forecast` פעם אחת. הריצה קוראת את הרשימה (עדיין ריקה) וכותבת את `SUBSCRIBE_URL` לאתר.

### בטלפון

1. פתחו את האתר.
2. באייפון: שיתוף ← **הוסף למסך הבית**, ופתחו משם. התראות באייפון עובדות רק ככה (iOS 16.4 ומעלה).
3. בנקודות, סמנו כוכב על המקומות שחשובים לכם. אפשר גם להוסיף נחל שלם בהגדרות.
4. בהגדרות, «הפעל התראות במכשיר הזה».
5. «שלח בדיקה» מראה התראה מקומית בלבד. התראה אמיתית יוצאת מהבדיקה השעתית, כשהסיכוי עובר את הסף.

### דרכים אחרות

- חשבון Cloudflare חינם (Worker ו-KV). צריך להירשם ל-Cloudflare. אין חובה בכרטיס אשראי.
- להדביק רשומה אחת ידנית אל `subscriptions/subscriptions.json`. מתאים רק למכשיר שלכם, כי הקובץ במאגר הציבורי וכולל את כתובת ההתראה של המכשיר.

## מגבלות

- המקור הוא תחזית Open-Meteo (רשת של כעשירית מעלה), לא רדאר של השירות המטאורולוגי.
- GitHub מריץ את הבדיקה השעתית «בערך» בזמן. לפעמים היא מאחרת בכמה דקות עד חצי שעה.
- אם אין שום פעילות במאגר במשך 60 יום, GitHub מכבה ריצות מתוזמנות. העדכון השעתי עצמו נחשב פעילות.
- זה כלי עזר. זה לא אזהרה רשמית. המודל אומן על נתוני עבר ורץ כאן על תחזית, אז יש פער.
- חלק מקואורדינטות הנקודות מסומנות כ«לאמת» ועדיין דורשות בדיקה בשטח.
- האתר ציבורי. קבצי הנתונים, כולל נקודות התצפית, גלויים לכולם.
