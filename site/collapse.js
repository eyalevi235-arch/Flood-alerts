// Per-overlay hide/show buttons. State is kept in localStorage (key ui_hide_<name>).
(function(){
 'use strict';
 function get(k){try{return localStorage.getItem('ui_hide_'+k)==='1';}catch(e){return false;}}
 function set(k,v){try{localStorage.setItem('ui_hide_'+k,v?'1':'0');}catch(e){}}
 function btn(cls,text,label){var b=document.createElement('button');b.type='button';b.className=cls;b.textContent=text;b.setAttribute('aria-label',label);b.title=label;return b;}
 // box: element to hide. chipHost: where the reopen chip goes. def: default hidden state.
 function wire(name,box,chipText,chipLabel,opts){
  if(!box)return;
  opts=opts||{};
  var x=btn('ui-x','×','הסתר');
  if(opts.inline)x.classList.add('ui-x-inline');
  box.insertBefore(x,box.firstChild);
  var chip=btn('ui-chip ui-chip-'+name,chipText,chipLabel);
  (opts.chipHost||box.parentNode).insertBefore(chip,opts.chipHost?null:box.nextSibling);
  function apply(h){box.classList.toggle('ui-hidden',h);chip.hidden=!h;document.body.classList.toggle('hid-'+name,h);}
  x.addEventListener('click',function(ev){ev.stopPropagation();set(name,true);apply(true);});
  chip.addEventListener('click',function(ev){ev.stopPropagation();set(name,false);apply(false);});
  apply(get(name));
 }
 function q(s){return document.querySelector(s);}
 wire('ctl',q('#ctl'),'⚙ שכבות','הצג את פאנל השכבות');
 wire('legend',q('#legend'),'🎨 מקרא','הצג את המקרא');
 wire('legal',q('#legal'),'ⓘ','הצג את הבהרת השימוש');
 wire('snap',q('#snap-hint'),'ⓘ הצמדה','הצג הסבר הצמדה',{inline:true});
 // Leaflet attribution is created asynchronously in init().
 var tries=0;
 (function waitAttr(){
  var a=q('#map .leaflet-control-attribution');
  if(!a){if(++tries<200)setTimeout(waitAttr,100);return;}
  var wrap=document.createElement('div');wrap.className='ui-attr-wrap leaflet-control';
  a.parentNode.insertBefore(wrap,a);wrap.appendChild(a);if(window.L&&L.DomEvent){L.DomEvent.disableClickPropagation(wrap);}
  // Leaflet rewrites a.innerHTML on every update, so the × button lives outside it.
  var x=btn('ui-x ui-x-attr','×','הסתר קרדיטים');wrap.insertBefore(x,a);
  var chip=btn('ui-chip ui-chip-attr','©','הצג קרדיטים (OpenStreetMap, GeoNames)');wrap.appendChild(chip);
  function apply(h){a.classList.toggle('ui-hidden',h);x.hidden=h;chip.hidden=!h;}
  x.addEventListener('click',function(){set('attr',true);apply(true);});
  chip.addEventListener('click',function(){set('attr',false);apply(false);});
  apply(get('attr'));
 })();
})();
