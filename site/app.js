const _u=new URLSearchParams(location.search).get('uid');if(_u)localStorage.uid=_u;
const $=s=>document.querySelector(s);let UID=localStorage.uid||(localStorage.uid='u'+Math.random().toString(36).slice(2,10));
let CFG,PREFS,VPS=[],map,riskL,streamL,vpL;
const SRC=new URLSearchParams(location.search).get('src')||'live';const api=p=>fetch(p,{cache:'no-cache'}).then(r=>{if(!r.ok)throw r.status;return r.json()});const jget=(p,d)=>api(p).catch(()=>d);
// static hosting (GitHub Pages): all data are relative JSON files written by the hourly Action; prefs live in localStorage
const loadPrefs=()=>{try{return Object.assign({points:[],streams:[],threshold:0.3},JSON.parse(localStorage.prefs||'{}'))}catch(e){return{points:[],streams:[],threshold:0.3}}};
let ALL=null;const allAlerts=async()=>ALL||(ALL=await jget(SRC=='demo'?'data/alerts_demo.json':'data/alerts_latest.json',{issued:null,source:null,stub:true,alerts:[]}));
const norm=x=>String(x||'').replace('נחל ','').trim();
const col=p=>p==null?'#bbb':p>=.7?'#7b0000':p>=.5?'#d7301f':p>=.3?'#fc8d59':p>=.1?'#fdd835':'#bbb';
const fmtH=h=>h==null?'—':h<1?'פחות משעה':`~${Math.round(h)} שעות`;
function show(p){document.querySelectorAll('.page').forEach(e=>e.classList.toggle('on',e.id=='p-'+p));document.querySelectorAll('nav button').forEach(b=>b.classList.toggle('on',b.dataset.p==p));location.hash=p;if(p=='map')setTimeout(()=>map.invalidateSize(),50);if(p=='alerts')loadAlerts();if(p=='set')renderSet();}
document.querySelectorAll('nav button').forEach(b=>b.onclick=()=>show(b.dataset.p));
async function init(){
 CFG=await jget('data/config.json',{vapid_public:'',risk_dates:[],live:null});PREFS=loadPrefs();
 map=L.map('map',{zoomControl:false}).setView([30.9,35.0],8);L.control.zoom({position:'bottomleft'}).addTo(map);
 L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{attribution:'© OpenStreetMap',maxZoom:17}).addTo(map);
 $('#date').innerHTML=`<option value="live">תחזית 48 שעות${CFG.live?' ('+CFG.live+')':''}</option>`+CFG.risk_dates.slice().reverse().map(d=>`<option>${d}</option>`).join('');
 $('#date').onchange=loadRisk;$('#per').onchange=loadRisk;
 api('data/streams.geojson').then(g=>{streamL=L.geoJSON(g,{style:{color:'#1565c0',weight:1.2,opacity:.7},interactive:false}).addTo(map)});
 await loadRisk();VPS=await jget('data/viewpoints.json',[]);if(SRC=='demo'){const A=await allAlerts();const m={};A.alerts.forEach(a=>m[a.point]=a);VPS.forEach(v=>v.current=m[v.id]);}drawVP();renderPoints();
 $('#q').oninput=renderPoints;$('#hdr').textContent='עודכן '+new Date().toLocaleTimeString('he-IL',{hour:'2-digit',minute:'2-digit'});
 if(location.hash.slice(1))show(location.hash.slice(1));
}
async function loadRisk(){const d=$('#date').value||'live';const g0=await jget(d=='live'?'data/risk_live.geojson':`data/risk_${d}.geojson`,null)||await jget('data/basins.geojson',{type:'FeatureCollection',features:[]});const g={...g0,features:g0.features.filter(x=>$('#per').checked||!x.properties.perennial)};
 if(riskL)map.removeLayer(riskL);
 riskL=L.geoJSON(g,{style:f=>{const p=f.properties;return{color:'#333',weight:.4,fillOpacity:p.perennial?.15:.5,fillColor:p.perennial?'#999':col(p.risk??p.risk_raw)}},
  onEachFeature:(f,l)=>{const p=f.properties;l.bindPopup(`<b>${p.name_he||p.main_nahal||'אגן'}</b><br>סיכוי: ${p.risk!=null?Math.round(p.risk*100)+'%':(p.risk_raw!=null?Math.round(p.risk_raw*100)+'% (גולמי)':'—')}${p.eta_peak_rain?'<br>שיא גשם צפוי: '+p.eta_peak_rain:''}<br>גשם באירוע: ${p.event_rain_mm??'—'} מ"מ<br>שטח: ${Math.round(p.area_dem||0)} קמ"ר${p.perennial?'<br><i>נחל איתן</i>':''}`)}}).addTo(map);riskL.bringToBack();}
function drawVP(){if(vpL)map.removeLayer(vpL);vpL=L.layerGroup(VPS.map(v=>L.circleMarker([v.lat,v.lon],{radius:7,color:'#fff',weight:2,fillColor:v.current&&v.current.prob>=PREFS.threshold?'#c0392b':'#1e88e5',fillOpacity:1}).bindPopup(()=>cardHTML(v,true)))).addTo(map);}
const fav=id=>PREFS.points.includes(id);
function cardHTML(v,short){const c=v.current||{};const fw=(v.first_waves||[]);
 return `<div class="card" style="${short?'box-shadow:none;padding:0':''}"><span class="star ${fav(v.id)?'on':''}" onclick="toggleFav('${v.id}')">★</span>
 <h3>${v.name_he}</h3><div class="muted">${v.nahal} · ${v.region}${v.basin_name?' · אגן: '+v.basin_name:''}${v.upstream_km2?' · '+Math.round(v.upstream_km2)+' קמ"ר':''}</div>
 <p><b>סיכוי כעת:</b> ${c.prob!=null?Math.round(c.prob*100)+'%':'—'} · <b>גל ראשון:</b> ${fmtH(c.hours_until_first_wave)}${c.eta_first_wave?' ('+c.eta_first_wave+')':''}</p>
 <p><b>איך מגיעים:</b> ${v.access||'—'}</p>${v.safety?`<p class="muted">⚠️ ${v.safety}</p>`:''}
 <a href="https://www.google.com/maps/dir/?api=1&destination=${v.lat},${v.lon}" target="_blank">ניווט 🧭</a> · <a href="https://waze.com/ul?ll=${v.lat},${v.lon}&navigate=yes" target="_blank">Waze</a>
 ${short?'':(fw.length?`<details><summary>זמני גל ראשון היסטוריים (${fw.length})</summary><table><tr><th>תאריך</th><th>מקום</th><th>שעה</th><th>שעות מתחילת גשם</th></tr>${fw.map(f=>`<tr><td>${f.date}</td><td>${f.place}</td><td>${f.time_il}</td><td>${f.lag_from_onset_h===''?'—':f.lag_from_onset_h}</td></tr>`).join('')}</table></details>`:'<div class="muted">אין עדיין זמני גל ראשון מתועדים</div>')}</div>`}
function renderPoints(){const q=($('#q').value||'').trim();$('#plist').innerHTML=VPS.filter(v=>!q||(v.name_he+v.nahal+v.region).includes(q)).sort((a,b)=>fav(b.id)-fav(a.id)).map(v=>cardHTML(v)).join('');}
async function savePrefs(){localStorage.prefs=JSON.stringify(PREFS);syncSub();renderPoints();drawVP();renderSet();}
function toggleFav(id){PREFS.points=fav(id)?PREFS.points.filter(x=>x!=id):[...PREFS.points,id];savePrefs();}
function addStream(){const s=$('#snew').value.trim();if(s&&!PREFS.streams.includes(s)){PREFS.streams.push(s);savePrefs();}$('#snew').value='';}
function rmStream(s){PREFS.streams=PREFS.streams.filter(x=>x!=s);savePrefs();}
function renderSet(){$('#favs').innerHTML=PREFS.points.map(id=>{const v=VPS.find(x=>x.id==id);return `<span class="chip">📍 ${v?v.name_he:id} <a onclick="toggleFav('${id}')">✕</a></span>`}).join('')+PREFS.streams.map(s=>`<span class="chip">〰️ ${s} <a onclick="rmStream('${s}')">✕</a></span>`).join('')||'אין מועדפים עדיין';
 $('#th').value=Math.round(PREFS.threshold*100);$('#thv').textContent=$('#th').value;}
$('#th').oninput=e=>$('#thv').textContent=e.target.value;$('#th').onchange=e=>{PREFS.threshold=e.target.value/100;savePrefs();};
async function loadAlerts(){const L=await allAlerts();const st={};PREFS.streams.forEach(s=>st[norm(s)]=s);const mine=[];
 for(const a of L.alerts){let why;if(PREFS.points.includes(a.point))why={via:'point'};else if(st[norm(a.nahal)])why={via:'stream',stream:st[norm(a.nahal)]};else continue;mine.push({...a,alert:a.prob>=PREFS.threshold,...why});}
 const A={...L,alerts:mine.sort((x,y)=>y.prob-x.prob),threshold:PREFS.threshold};
 let h=`<div class="muted">תחזית מ-${A.issued||'—'} · מקור: ${A.source||'—'}${A.stub?' · <b>מצב הדגמה (מנוע התחזית עוד לא זמין)</b>':''}</div>`;
 if(!A.alerts.length)h+=`<div class="card">אין נקודות מועדפות. סמנו ⭐ בנקודות או הוסיפו נחל בהגדרות.</div>`;
 for(const a of A.alerts){const r=a.rain_summary||{};const cls=a.alert?(a.prob>=.5?'hi':'mid'):'';
  const via=a.via=='stream'&&a.stream?`<div class="muted">במעקב דרך: ${a.stream}</div>`:'';
  h+=`<div class="card al ${cls}"><h3>${a.alert?`סיכוי גבוה לשיטפון ב${a.nahal}, הגל צפוי להגיע לנקודה "${a.name}" בעוד ${fmtH(a.hours_until_first_wave)}`:`${a.name} – אין התראה`}</h3>${via}
  <div>סיכוי: <b>${Math.round(a.prob*100)}%</b> (סף ${Math.round(A.threshold*100)}%) · ודאות: ${({low:'נמוכה',medium:'בינונית',high:'גבוהה'})[a.confidence]||'—'}</div>
  <div>גל ראשון: ${a.eta_first_wave||'—'} · שיא: ${a.eta_peak||'—'}</div>
  <div class="muted">גשם ממוצע באגן: ${r.basin_mean_mm??'—'} מ"מ · עוצמה מרבית: ${r.max_cell_mm_h??'—'} מ"מ/שעה · ספיקת שיא משוערת: ${r.q_peak_m3s??'—'} מק"ש</div>
  ${distHTML(r.contributing_by_travel_time)}</div>`}
 $('#alist').innerHTML=h;}
function distHTML(c){if(!c||typeof c!='object')return'';const e=Array.isArray(c)?c.map((x,i)=>[x.label??i,x.mm??x.value??x]):Object.entries(c);if(!e.length)return'';const m=Math.max(...e.map(x=>+x[1]||0))||1;
 return `<details><summary>פיזור הגשם באגן לפי זמן זרימה לנקודה</summary>${e.map(([k,v])=>`<div style="display:flex;gap:6px;align-items:center;font-size:12px"><span style="width:70px">${k}</span><div class="bar" style="width:${(+v||0)/m*70}%"></div><span>${typeof v=='number'?v.toFixed(1):v}</span></div>`).join('')}</details>`}
const b64=s=>{const p='='.repeat((4-s.length%4)%4);const r=atob((s+p).replace(/-/g,'+').replace(/_/g,'/'));return Uint8Array.from([...r].map(c=>c.charCodeAt(0)))};
async function enablePush(){try{const reg=await navigator.serviceWorker.ready;if(await Notification.requestPermission()!='granted')throw'לא ניתנה הרשאה';
 if(!CFG.vapid_public)throw'מפתח VAPID ציבורי חסר בהגדרות האתר';
 const s=await reg.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:b64(CFG.vapid_public)});localStorage.pushsub=JSON.stringify(s.toJSON());await syncSub(true);}catch(e){$('#pst').textContent='שגיאה: '+e}}
// Subscription record {uid,points,streams,threshold,push}. Needs a free write endpoint (CFG.subscribe_url, e.g. Google Apps Script) - static Pages cannot store it.
function subRecord(){return{uid:UID,points:PREFS.points,streams:PREFS.streams,threshold:PREFS.threshold,push:localStorage.pushsub?JSON.parse(localStorage.pushsub):null,updated:new Date().toISOString()}}
async function syncSub(verbose){if(!localStorage.pushsub)return;const rec=subRecord();
 if(CFG.subscribe_url){try{await fetch(CFG.subscribe_url,{method:'POST',mode:'no-cors',headers:{'Content-Type':'text/plain'},body:JSON.stringify(rec)});if(verbose)$('#pst').textContent='✔ התראות הופעלו – ההרשמה נשמרה (התראות נשלחות בבדיקה השעתית)';}catch(e){$('#pst').textContent='שגיאה בשמירת ההרשמה: '+e}}
 else if(verbose)$('#pst').innerHTML='✔ ההרשאה ניתנה, אבל עדיין אין שרת הרשמה. העתיקו את הרשומה:<br><textarea style="width:100%;height:70px" readonly>'+JSON.stringify(rec)+'</textarea>';}
async function testPush(){const reg=await navigator.serviceWorker.ready;reg.showNotification('בדיקת התראה',{body:'כך תיראה התראת שיטפון במכשיר הזה ✔',icon:'./icon-192.png',dir:'rtl',lang:'he'});$('#pst').textContent='הוצגה התראת בדיקה מקומית (התראות אמיתיות נשלחות מהבדיקה השעתית)';}
if('serviceWorker'in navigator)navigator.serviceWorker.register('./sw.js');init();
