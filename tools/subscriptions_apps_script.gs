// Free subscription store: Google Apps Script web app bound to a Google Sheet (no card).
// Deploy: Extensions > Apps Script, paste, set Script Property TOKEN, Deploy > Web app (execute as me, access: Anyone).
// PWA POSTs a JSON record {uid,points,streams,threshold,push}; Action GETs ?token=TOKEN -> JSON list.
function doPost(e){const r=JSON.parse(e.postData.contents);if(!r.uid||!r.push||!r.push.endpoint)return ContentService.createTextOutput('bad');
 const sh=SpreadsheetApp.getActiveSpreadsheet().getSheets()[0];const v=sh.getDataRange().getValues();
 for(let i=0;i<v.length;i++)if(v[i][0]===r.uid){sh.getRange(i+1,1,1,3).setValues([[r.uid,JSON.stringify(r),new Date()]]);return ContentService.createTextOutput('ok');}
 sh.appendRow([r.uid,JSON.stringify(r),new Date()]);return ContentService.createTextOutput('ok');}
function doGet(e){if(e.parameter.token!==PropertiesService.getScriptProperties().getProperty('TOKEN'))return ContentService.createTextOutput('[]');
 const v=SpreadsheetApp.getActiveSpreadsheet().getSheets()[0].getDataRange().getValues();const out=[];
 v.forEach(r=>{try{out.push(JSON.parse(r[1]))}catch(_){}});return ContentService.createTextOutput(JSON.stringify(out)).setMimeType(ContentService.MimeType.JSON);}
