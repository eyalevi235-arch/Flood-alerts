const $=s=>document.querySelector(s);
const SRC=new URLSearchParams(location.search).get('src')==='demo'?'demo':'live';
let UID=localStorage.uid;
if(!/^u[a-z0-9]{6,20}$/.test(UID||'')){UID='u'+Math.random().toString(36).slice(2,10);localStorage.uid=UID;}
let CFG,PREFS=loadPrefs(),VPS=[],map,riskL,streamL,vpL,baseL;
const BASEMAPS={
 topo:{url:'https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}',attr:'© Esri — Esri, DeLorme, NAVTEQ, TomTom, Intermap, iPC, USGS, FAO, NPS, NRCAN, GeoBase, Kadaster NL, Ordnance Survey, Esri Japan, METI, Esri China (Hong Kong), GIS User Community',maxZoom:17},
 street:{url:'https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png',subdomains:'abcd',attr:'© <a href="https://www.openstreetmap.org/copyright" rel="noopener noreferrer">OpenStreetMap</a> © <a href="https://carto.com/attributions" rel="noopener noreferrer">CARTO</a>',maxZoom:19},
 sat:{url:'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',attr:'© Esri — Esri, Maxar, Earthstar Geographics, GIS User Community',maxZoom:17}
};
function addBasemap(target,kind){
 const spec=BASEMAPS[kind]||BASEMAPS.topo;
 const layer=L.tileLayer(spec.url,{attribution:spec.attr,maxZoom:spec.maxZoom,subdomains:spec.subdomains||'abc'});
 layer.addTo(target);
 layer.bringToBack();
 return layer;
}
function northOn(){const n=$('#north');return !n||n.checked;}
function northColor(p){if(p>0.6)return '#08306b';if(p>=0.3)return '#2171b5';if(p>=0.1)return '#6baed6';return '#c6dbef';}
function northWeight(a,p){
 let w=1;
 if(a>=500)w=4;else if(a>20)w=1+3*(Math.log(a/20)/Math.log(500/20));
 if(p>0.6)w=Math.min(5,w+0.8);
 return w;
}
let northL=null;
async function loadNorth(){
 if(!map)return;
 if(northL){map.removeLayer(northL);northL=null;}
 if(!northOn())return;
 const gj=await jget('data/channel_segments_nondesert.geojson',null);
 if(!gj||!Array.isArray(gj.features))return;
 const risk=await jget('data/segment_risk_nondesert.json',null);
 const probs=risk&&Array.isArray(risk.p)?risk.p:[];
 northL=L.geoJSON(gj,{interactive:false,style:f=>{
  const pr=f.properties||{};const id=Number(pr.id);const prob=Number.isFinite(probs[id])?Number(probs[id]):0;const a=Number(pr.a)||0;
  return {color:northColor(prob),weight:northWeight(a,prob),opacity:.95,dashArray:pr.p?null:'6 5',interactive:false};
 }}).addTo(map);
 if(vpL)vpL.bringToFront();
}
function setMainBase(kind){
 if(!BASEMAPS[kind])kind='topo';
 if(baseL)map.removeLayer(baseL);
 baseL=addBasemap(map,kind);
 if(riskL)riskL.bringToFront();
 if(streamL)streamL.bringToFront();
 if(vpL)vpL.bringToFront();
}
const api=p=>fetch(p,{cache:'no-cache'}).then(r=>{if(!r.ok)throw r.status;return r.json()});
const jget=(p,d)=>api(p).catch(()=>d);
const PAGES=['map','points','alerts','report','feedback','set'];
function el(tag,cls,text){const n=document.createElement(tag);if(cls)n.className=cls;if(text!=null)n.textContent=text;return n;}
function clear(n){while(n&&n.firstChild)n.removeChild(n.firstChild);}
function txt(v,fallback){if(v==null||v==='')return fallback==null?'':String(fallback);return String(v);}
function num(v){const n=Number(v);return Number.isFinite(n)?n:null;}
function loadPrefs(){
 const base={points:[],streams:[],threshold:0.3};
 try{
  const raw=JSON.parse(localStorage.prefs||'{}');
  const points=Array.isArray(raw.points)?raw.points.filter(p=>/^VP\d{2}$/.test(p)).slice(0,40):[];
  const streams=Array.isArray(raw.streams)?raw.streams.filter(s=>typeof s==='string'&&s.length>=1&&s.length<=40&&!/[\u0000-\u001f<>]/.test(s)).slice(0,12):[];
  let threshold=Number(raw.threshold);if(!Number.isFinite(threshold)||threshold<0.05||threshold>0.9)threshold=0.3;
  return {points,streams,threshold};
 }catch(e){return base;}
}
let ALL=null;
const allAlerts=async()=>ALL||(ALL=await jget(SRC==='demo'?'data/alerts_demo.json':'data/alerts_latest.json',{issued:null,source:null,stub:true,alerts:[]}));
const norm=x=>String(x||'').replace('נחל ','').trim();
const col=p=>p==null?'#bbb':p>=.7?'#7b0000':p>=.5?'#d7301f':p>=.3?'#fc8d59':p>=.1?'#fdd835':'#bbb';
const fmtH=h=>h==null?'—':h<1?'פחות משעה':`~${Math.round(h)} שעות`;
function show(p){
 if(!PAGES.includes(p))p='map';
 document.querySelectorAll('.page').forEach(e=>e.classList.toggle('on',e.id==='p-'+p));
 document.querySelectorAll('nav button').forEach(b=>b.classList.toggle('on',b.dataset.p===p));
 location.hash=p;
 if(p==='map'&&map)setTimeout(()=>map.invalidateSize(),50);
 if(p==='alerts')loadAlerts();
 if(p==='set')renderSet();
 if(p==='report'&&typeof openReport==='function')openReport();
 if(p==='feedback'&&typeof openFeedback==='function')openFeedback();
}
function finiteCoord(lat,lon){
 lat=Number(lat);lon=Number(lon);
 if(!Number.isFinite(lat)||!Number.isFinite(lon))return null;
 if(lat<29||lat>34||lon<34||lon>36.5)return null;
 return [lat,lon];
}
function extLink(href,text){const a=el('a',null,text);a.href=href;a.target='_blank';a.rel='noopener noreferrer';return a;}
function navLinks(lat,lon){
 const c=finiteCoord(lat,lon);if(!c)return [];
 const g=new URL('https://www.google.com/maps/dir/');g.searchParams.set('api','1');g.searchParams.set('destination',c[0]+','+c[1]);
 const w=new URL('https://waze.com/ul');w.searchParams.set('ll',c[0]+','+c[1]);w.searchParams.set('navigate','yes');
 return [[g.href,'ניווט 🧭'],[w.href,'Waze']];
}
function dateOk(d){return /^\d{4}-\d{2}-\d{2}$/.test(d);}
async function init(){
 CFG=await jget('data/config.json',{vapid_public:'',risk_dates:[],live:null,subscribe_url:''});
 PREFS=loadPrefs();
 map=L.map('map',{zoomControl:false}).setView([30.9,35.0],8);
 L.control.zoom({position:'bottomleft'}).addTo(map);
 setMainBase('topo');
 $('#base').onchange=()=>setMainBase($('#base').value);
 const date=$('#date');clear(date);
 const liveOpt=el('option',null,'תחזית 48 שעות'+(CFG.live?' ('+txt(CFG.live)+')':''));liveOpt.value='live';date.appendChild(liveOpt);
 (Array.isArray(CFG.risk_dates)?CFG.risk_dates:[]).filter(dateOk).slice().reverse().forEach(d=>{const o=el('option',null,d);o.value=d;date.appendChild(o);});
 date.onchange=loadRisk;$('#per').onchange=loadRisk;
 api('data/channel_segments.geojson').then(g=>{streamL=L.geoJSON(g,{style:{color:'#1565c0',weight:1.6,opacity:.85},interactive:false}).addTo(map)});
 const north=$('#north');
 if(north){
  if(localStorage.north_layer==='0')north.checked=false;
  north.onchange=()=>{localStorage.north_layer=north.checked?'1':'0';loadNorth();};
 }
 loadNorth();
 await loadRisk();
 VPS=await jget('data/viewpoints.json',[]);
 if(!Array.isArray(VPS))VPS=[];
 if(SRC==='demo'){const A=await allAlerts();const m={};(A.alerts||[]).forEach(a=>{if(a&&a.point)m[a.point]=a;});VPS.forEach(v=>{if(m[v.id])v.current=m[v.id];});}
 drawVP();renderPoints();renderSet();
 $('#q').oninput=renderPoints;
 $('#hdr').textContent='עודכן '+new Date().toLocaleTimeString('he-IL',{hour:'2-digit',minute:'2-digit'});
 const hash=location.hash.slice(1);if(PAGES.includes(hash))show(hash);
 if(typeof bindTap==='function')bindTap(map);
 if(typeof drawMyPoints==='function')drawMyPoints();
 if(typeof resnapNorthPoints==='function')resnapNorthPoints();
}
async function loadRisk(){
 const chosen=$('#date').value;
 const file=chosen==='live'||!dateOk(chosen)?'data/risk_live.geojson':`data/risk_${chosen}.geojson`;
 const g0=await jget(file,null)||await jget('data/basins.geojson',{type:'FeatureCollection',features:[]});
 const features=(g0&&Array.isArray(g0.features)?g0.features:[]).filter(x=>$('#per').checked||!(x.properties&&x.properties.perennial));
 const g={...g0,features};
 if(riskL)map.removeLayer(riskL);
 riskL=L.geoJSON(g,{interactive:false,style:f=>{const p=f.properties||{};return{color:'#333',weight:.4,fillOpacity:p.perennial?.15:.5,fillColor:p.perennial?'#999':col(p.risk??p.risk_raw),interactive:false};}}).addTo(map);
 riskL.bringToBack();
}
function riskPopup(p){
 const box=el('div');
 box.appendChild(el('b',null,txt(p.name_he||p.main_nahal,'אגן')));
 const risk=num(p.risk),raw=num(p.risk_raw);
 box.appendChild(el('div',null,'סיכוי: '+(risk!=null?Math.round(risk*100)+'%':(raw!=null?Math.round(raw*100)+'% (גולמי)':'—'))));
 if(p.eta_peak_rain)box.appendChild(el('div',null,'שיא גשם צפוי: '+txt(p.eta_peak_rain)));
 const rain=num(p.event_rain_mm),area=num(p.area_dem);
 box.appendChild(el('div',null,'גשם באירוע: '+(rain!=null?String(rain):'—')+' מ"מ'));
 box.appendChild(el('div',null,'שטח: '+Math.round(area||0)+' קמ"ר'));
 if(p.perennial)box.appendChild(el('div',null,'נחל איתן'));
 return box;
}
function drawVP(){
 if(vpL)map.removeLayer(vpL);
 vpL=L.layerGroup(VPS.filter(v=>finiteCoord(v.lat,v.lon)).map(v=>{
  const c=finiteCoord(v.lat,v.lon);
  const mk=L.circleMarker(c,{radius:7,color:'#fff',weight:2,fillColor:v.current&&num(v.current.prob)>=PREFS.threshold?'#c0392b':'#1e88e5',fillOpacity:1}).bindPopup(()=>cardEl(v,true));
  mk.on('click',ev=>{if(ev.originalEvent)ev.originalEvent.__vp=1;});
  return mk;
 })).addTo(map);
}
const fav=id=>PREFS.points.includes(id);
function cardEl(v,short){
 const c=v.current||{};const fw=Array.isArray(v.first_waves)?v.first_waves.slice(0,12):[];
 const root=el('div',short?'card tight':'card');
 const star=el('button','star'+(fav(v.id)?' on':''),'★');star.type='button';
 star.addEventListener('click',()=>toggleFav(String(v.id||'')));
 root.appendChild(star);
 if(fav(v.id)&&!short){
  const off=el('button','btn alt','בטל התראות');off.type='button';
  off.addEventListener('click',()=>cancelPointAlerts(String(v.id||'')));
  root.appendChild(off);
 }
 root.appendChild(el('h3',null,txt(v.name_he,'נקודה')));
 const bits=[txt(v.nahal),txt(v.region)];
 if(v.basin_name)bits.push('אגן: '+txt(v.basin_name));
 const up=num(v.upstream_km2);if(up!=null)bits.push(Math.round(up)+' קמ"ר');
 root.appendChild(el('div','muted',bits.filter(Boolean).join(' · ')));
 const prob=num(c.prob);
 const p1=el('p');
 p1.appendChild(el('b',null,'סיכוי כעת: '));
 p1.appendChild(document.createTextNode((prob!=null?Math.round(prob*100)+'%':'—')+' · '));
 p1.appendChild(el('b',null,'גל ראשון: '));
 p1.appendChild(document.createTextNode(fmtH(num(c.hours_until_first_wave))+(c.eta_first_wave?' ('+txt(c.eta_first_wave)+')':'')));
 root.appendChild(p1);
 root.appendChild(el('p',null,'איך מגיעים: '+txt(v.access,'—')));
 if(v.safety)root.appendChild(el('p','muted','⚠️ '+txt(v.safety)));
 const links=navLinks(v.lat,v.lon);
 if(links.length){
  const line=el('p');
  links.forEach((pair,i)=>{if(i)line.appendChild(document.createTextNode(' · '));line.appendChild(extLink(pair[0],pair[1]));});
  root.appendChild(line);
 }
 if(!short){
  if(fw.length){
   const det=el('details');det.appendChild(el('summary',null,'זמני גל ראשון היסטוריים ('+fw.length+')'));
   const table=el('table');const hr=el('tr');['תאריך','מקום','שעה','שעות מתחילת גשם'].forEach(h=>hr.appendChild(el('th',null,h)));table.appendChild(hr);
   fw.forEach(f=>{const tr=el('tr');[f.date,f.place,f.time_il,f.lag_from_onset_h===''||f.lag_from_onset_h==null?'—':f.lag_from_onset_h].forEach(cell=>tr.appendChild(el('td',null,txt(cell,'—'))));table.appendChild(tr);});
   det.appendChild(table);root.appendChild(det);
  }else root.appendChild(el('div','muted','אין עדיין זמני גל ראשון מתועדים'));
 }
 return root;
}
function renderPoints(){
 const q=($('#q').value||'').trim();const host=$('#plist');clear(host);
 VPS.filter(v=>!q||(txt(v.name_he)+txt(v.nahal)+txt(v.region)).includes(q)).sort((a,b)=>fav(b.id)-fav(a.id)).forEach(v=>host.appendChild(cardEl(v,false)));
}
function savePrefs(){localStorage.prefs=JSON.stringify(PREFS);syncSub(false);renderPoints();drawVP();renderSet();}
function toggleFav(id){if(!/^VP\d{2}$/.test(id))return;PREFS.points=fav(id)?PREFS.points.filter(x=>x!==id):[...PREFS.points,id].slice(0,40);savePrefs();}
function addStream(){
 const s=$('#snew').value.trim();
 if(s&&s.length<=40&&!/[\u0000-\u001f<>]/.test(s)&&!PREFS.streams.includes(s)&&PREFS.streams.length<12){PREFS.streams.push(s);savePrefs();}
 $('#snew').value='';
}
function rmStream(s){PREFS.streams=PREFS.streams.filter(x=>x!==s);savePrefs();}
function confirmUnsub(msg){
 const pst=$('#pst');if(pst)pst.textContent=msg;
 const page=$('#unsub-msg');if(page)page.textContent=msg;
}
function cancelPointAlerts(id){
 if(!/^VP\d{2}$/.test(id)||!fav(id))return;
 PREFS.points=PREFS.points.filter(x=>x!==id);
 savePrefs();
 confirmUnsub('ההתראות לנקודה זו בוטלו.');
}
function cancelStreamAlerts(s){
 PREFS.streams=PREFS.streams.filter(x=>x!==s);
 savePrefs();
 confirmUnsub('ההתראות לנחל זה בוטלו.');
}
async function unsubscribeAll(){
 const pst=$('#pst');
 let endpoint='';
 try{
  if('serviceWorker' in navigator){
   const reg=await navigator.serviceWorker.ready;
   const sub=await reg.pushManager.getSubscription();
   if(sub){endpoint=sub.endpoint||'';await sub.unsubscribe();}
  }
 }catch(e){}
 if(!endpoint){const saved=storedPush();if(saved)endpoint=saved.endpoint;}
 if(endpoint&&hostOk(endpoint)){try{await postSub({action:'unsubscribe',push:{endpoint:endpoint}});}catch(e){}}
 localStorage.removeItem('pushsub');
 localStorage.removeItem('myPoints');
 PREFS.points=[];PREFS.streams=[];
 savePrefs();
 if(typeof drawMyPoints==='function')drawMyPoints();
 const msg='כל ההתראות בוטלו. ההרשמה נמחקה מהמכשיר ומהשרת.';
 if(pst)pst.textContent=msg;
 const page=$('#unsub-msg');if(page)page.textContent=msg;
}
function renderSet(){
 const host=$('#favs');if(!host)return;clear(host);
 if(!PREFS.points.length&&!PREFS.streams.length)host.textContent='אין מועדפים עדיין';
 PREFS.points.forEach(id=>{const v=VPS.find(x=>x.id===id);const chip=el('span','chip','📍 '+(v?txt(v.name_he):id)+' ');const b=el('button','unsub','בטל התראות');b.type='button';b.addEventListener('click',()=>cancelPointAlerts(id));chip.appendChild(b);host.appendChild(chip);});
 PREFS.streams.forEach(s=>{const chip=el('span','chip','〰️ '+s+' ');const b=el('button','unsub','בטל התראות');b.type='button';b.addEventListener('click',()=>cancelStreamAlerts(s));chip.appendChild(b);host.appendChild(chip);});
 const th=$('#th'),thv=$('#thv');
 if(th&&thv){th.value=String(Math.round(PREFS.threshold*100));thv.textContent=th.value;}
 if(typeof renderMyPointList==='function')renderMyPointList();
}
function distEl(c){
 if(!c||typeof c!=='object')return null;
 const entries=Array.isArray(c)?c.map((x,i)=>[x&&x.label!=null?x.label:i,x&&(x.mm!=null?x.mm:x.value)]):Object.entries(c);
 const rows=entries.filter(x=>x[0]!=null).slice(0,8);
 if(!rows.length)return null;
 const max=Math.max(...rows.map(x=>Number(x[1])||0))||1;
 const det=el('details');det.appendChild(el('summary',null,'פיזור הגשם באגן לפי זמן זרימה לנקודה'));
 rows.forEach(([k,v])=>{
  const row=el('div','dist-row');row.appendChild(el('span','dist-k',txt(k)));
  const slot=el('span','bar-slot');const bar=el('span','bar bar-w-'+Math.max(0,Math.min(10,Math.round((Number(v)||0)/max*10))));
  slot.appendChild(bar);row.appendChild(slot);row.appendChild(el('span',null,typeof v==='number'?v.toFixed(1):txt(v)));
  det.appendChild(row);
 });
 return det;
}
async function loadAlerts(){
 const L=await allAlerts();const alerts=Array.isArray(L.alerts)?L.alerts:[];
 const st={};PREFS.streams.forEach(s=>st[norm(s)]=s);const mine=[];
 for(const a of alerts){
  if(!a)continue;
  let why;if(PREFS.points.includes(a.point))why={via:'point'};else if(st[norm(a.nahal)])why={via:'stream',stream:st[norm(a.nahal)]};else continue;
  mine.push({...a,alert:num(a.prob)>=PREFS.threshold,...why});
 }
 mine.sort((x,y)=>(num(y.prob)||0)-(num(x.prob)||0));
 const host=$('#alist');clear(host);
 const head=el('div','muted','תחזית מ-'+txt(L.issued,'—')+' · מקור: '+txt(L.source,'—')+(L.stub?' · מצב הדגמה (מנוע התחזית עוד לא זמין)':''));
 host.appendChild(head);
 if(!mine.length && !(typeof loadMyPoints==='function' && loadMyPoints().length)){host.appendChild(el('div','card','אין נקודות מועדפות. סמנו ⭐ בנקודות, הוסיפו נחל, או הקישו על המפה ושמרו נקודה.'));return;}
 const conf={low:'נמוכה',medium:'בינונית',high:'גבוהה'};
 for(const a of mine){
  const r=a.rain_summary||{};const prob=num(a.prob)||0;const cls=a.alert?(prob>=.5?'hi':'mid'):'';
  const card=el('div','card al'+(cls?' '+cls:''));
  const title=a.alert?`סיכוי גבוה לשיטפון ב${txt(a.nahal)}, הגל צפוי להגיע לנקודה "${txt(a.name)}" בעוד ${fmtH(num(a.hours_until_first_wave))}`:`${txt(a.name)} – אין התראה`;
  card.appendChild(el('h3',null,title));
  if(a.via==='stream'&&a.stream)card.appendChild(el('div','muted','במעקב דרך: '+txt(a.stream)));
  card.appendChild(el('div',null,'סיכוי: '+Math.round(prob*100)+'% (סף '+Math.round(PREFS.threshold*100)+'%) · ודאות: '+(conf[a.confidence]||'—')));
  card.appendChild(el('div',null,'גל ראשון: '+txt(a.eta_first_wave,'—')+' · שיא: '+txt(a.eta_peak,'—')));
  card.appendChild(el('div','muted','גשם ממוצע באגן: '+txt(r.basin_mean_mm,'—')+' מ"מ · עוצמה מרבית: '+txt(r.max_cell_mm_h,'—')+' מ"מ/שעה · ספיקת שיא משוערת: '+txt(r.q_peak_m3s,'—')+' מק"ש'));
  const dist=distEl(r.contributing_by_travel_time);if(dist)card.appendChild(dist);
  host.appendChild(card);
 }
 if(typeof appendMyPointAlerts==='function') await appendMyPointAlerts(host);
}
function hostOk(endpoint){
 try{
  const u=new URL(endpoint);
  if(u.protocol!=='https:'||u.username||u.password)return false;
  const h=u.hostname.toLowerCase().replace(/\.$/,'');
  if(h==='fcm.googleapis.com'||h==='updates.push.services.mozilla.com')return true;
  if(h.endsWith('.push.apple.com')&&h.length>'.push.apple.com'.length)return true;
  if(h.endsWith('.notify.windows.com')&&h.length>'.notify.windows.com'.length)return true;
  return false;
 }catch(e){return false;}
}
function subscribeUrlOk(url){
 try{const u=new URL(url);return u.protocol==='https:'&&(u.hostname==='script.google.com'||u.hostname==='script.googleusercontent.com');}
 catch(e){return false;}
}
const b64=s=>{const p='='.repeat((4-s.length%4)%4);const r=atob((s+p).replace(/-/g,'+').replace(/_/g,'/'));return Uint8Array.from([...r].map(c=>c.charCodeAt(0)));};
function storedPush(){try{const p=JSON.parse(localStorage.pushsub||'null');return p&&hostOk(p.endpoint)?p:null;}catch(e){return null;}}
function subRecord(){return{action:'register',uid:UID,points:PREFS.points,streams:PREFS.streams,threshold:PREFS.threshold,custom:(typeof myPointsPayload==='function')?myPointsPayload():[],push:storedPush(),updated:new Date().toISOString()};}
async function postSub(body){
 if(!CFG||!subscribeUrlOk(CFG.subscribe_url))return false;
 await fetch(CFG.subscribe_url,{method:'POST',mode:'no-cors',headers:{'Content-Type':'text/plain'},body:JSON.stringify(body)});
 return true;
}
async function enablePush(){
 const pst=$('#pst');
 try{
  const reg=await navigator.serviceWorker.ready;
  if(await Notification.requestPermission()!=='granted')throw new Error('לא ניתנה הרשאה');
  if(!CFG.vapid_public)throw new Error('מפתח VAPID ציבורי חסר בהגדרות האתר');
  const s=await reg.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:b64(CFG.vapid_public)});
  const json=s.toJSON();
  if(!hostOk(json.endpoint))throw new Error('שירות ההתראות של הדפדפן הזה לא נתמך');
  localStorage.pushsub=JSON.stringify(json);
  const sent=await postSub(subRecord());
  pst.textContent=sent?'התראות הופעלו. ההרשמה נשמרה בשרת הפרטי, וההתראות נשלחות מהבדיקה השעתית.':'ההרשאה ניתנה במכשיר, אבל עדיין אין שרת הרשמה. בעל האתר צריך להגדיר כתובת Apps Script. אל תעתיקו את פרטי ההתראה לשום מקום ציבורי.';
 }catch(e){pst.textContent='שגיאה: '+(e&&e.message?e.message:e);}
}
async function syncSub(verbose){
 if(!storedPush())return;
 const sent=await postSub(subRecord());
 if(verbose){
  $('#pst').textContent=sent?'ההעדפות עודכנו בשרת ההרשמה.':'ההעדפות נשמרו במכשיר. שרת ההרשמה עדיין לא מוגדר, ופרטי ה-Push לא נשלחים לשום מקום.';
 }
}
async function testPush(){
 const reg=await navigator.serviceWorker.ready;
 reg.showNotification('בדיקת התראה',{body:'כך תיראה התראת שיטפון במכשיר הזה',icon:'./icon-192.png',dir:'rtl',lang:'he',actions:[{action:'unsubscribe',title:'בטל התראות'}],data:{url:location.href.split('#')[0]+'#alerts',settings:location.href.split('#')[0]+'#set'}});
 $('#pst').textContent='הוצגה התראת בדיקה מקומית. התראות אמיתיות נשלחות רק מהבדיקה השעתית.';
}
document.querySelectorAll('nav button').forEach(b=>b.addEventListener('click',()=>show(b.dataset.p)));
$('#gate-ok').addEventListener('click',()=>{localStorage.ack_disclaimer_v1='1';$('#gate').hidden=true;});
$('#add-stream').addEventListener('click',addStream);
$('#enable-push').addEventListener('click',()=>enablePush());
$('#test-push').addEventListener('click',()=>testPush());
$('#unsubscribe-all').addEventListener('click',()=>unsubscribeAll());
$('#th').addEventListener('input',e=>{$('#thv').textContent=e.target.value;});
$('#th').addEventListener('change',e=>{const v=Number(e.target.value);if(Number.isFinite(v)){PREFS.threshold=Math.min(0.9,Math.max(0.05,v/100));savePrefs();}});
if(localStorage.ack_disclaimer_v1==='1')$('#gate').hidden=true;
if('serviceWorker'in navigator)navigator.serviceWorker.register('./sw.js');
init();
