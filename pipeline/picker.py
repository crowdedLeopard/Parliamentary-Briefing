"""The keyword picker added to every briefing page (site.py puts it under the day bar).

It loads kw/<date>.json (keywords.site_payload) only when opened. Ticking suggested keywords,
adding one's own, or switching standing topics off re-screens the day's items in the browser,
at no cost. "Rewrite with these keywords" asks for the visitor's email address and sends it with
the chosen keywords to the separate regenerate service (worker/ and .github/workflows/regenerate.yml)
at REGEN_URL. Only approved addresses get a rewrite, one per person per edition; the page then
waits for it and links to the result. With no REGEN_URL the rewrite box is left out.
"""

from __future__ import annotations

import json
from html import escape as e

CSS = """<style>
.kw{--kw-g:light-dark(#0b6b4b,#3fb487);--kw-rule:light-dark(#d5ddd8,#24332c);--kw-mut:light-dark(#4d5752,#a9b8b0);
--kw-bg:light-dark(#fff,#0f1b16);--kw-tint:light-dark(#eaf4ef,#12231c);--kw-mark:light-dark(#fdf2dc,#4a3a12);
border-bottom:1px solid var(--kw-rule);padding:6px max(5vw,16px);font:15px/1.45 "Source Sans 3",system-ui,sans-serif;background:var(--kw-bg)}
.kw>summary{max-width:1240px;margin:0 auto;cursor:pointer;font-weight:700;color:var(--kw-g);list-style-position:inside}
.kw>summary small{font-weight:400;color:var(--kw-mut)}
.kw-in{max-width:1240px;margin:10px auto 6px;display:grid;gap:14px}
.kw h4{margin:0 0 6px;font:700 13px/1.2 "Source Sans 3",system-ui,sans-serif;letter-spacing:.06em;text-transform:uppercase;color:var(--kw-mut)}
.kw-chips{display:flex;flex-wrap:wrap;gap:6px}
.kw-chip{font:inherit;font-size:14px;border:1px solid var(--kw-rule);border-radius:99px;padding:3px 11px;background:transparent;color:inherit;cursor:pointer;text-align:left}
.kw-chip[aria-pressed=true]{background:var(--kw-g);border-color:var(--kw-g);color:light-dark(#fff,#06120d)}
.kw-chip small{opacity:.8}.kw-chip.kw-off[aria-pressed=false]{text-decoration:line-through;opacity:.7}
.kw-why{font-size:13px;color:var(--kw-mut);margin:6px 0 0;min-height:1.2em}
.kw-add{display:flex;flex-wrap:wrap;gap:6px}.kw-add input{font:inherit;flex:1 1 220px;padding:4px 8px;border:1px solid var(--kw-rule);border-radius:3px;background:transparent;color:inherit}
.kw-btn{font:inherit;font-weight:600;border:1px solid var(--kw-g);color:var(--kw-g);background:transparent;border-radius:3px;padding:4px 12px;cursor:pointer}
.kw-btn.kw-main{background:var(--kw-g);color:light-dark(#fff,#06120d)}.kw-btn[disabled]{opacity:.5;cursor:not-allowed}
.kw-sum{background:var(--kw-tint);border-radius:4px;padding:8px 12px;margin:0}
.kw-res{display:grid;gap:8px;margin:0;padding:0;list-style:none}.kw-res li{border-left:3px solid var(--kw-rule);padding:2px 0 2px 10px}
.kw-res li.kw-new{border-left-color:var(--kw-g)}.kw-res .kw-m{font-size:13px;color:var(--kw-mut)}.kw-res p{margin:2px 0 0;font-size:14px}
.kw-res mark{background:var(--kw-mark);color:inherit;padding:0 2px}
.kw-regen{border:1px solid var(--kw-rule);border-radius:4px;padding:10px 12px;display:grid;gap:6px;justify-items:start}
.kw-regen p{margin:0;font-size:14px;color:var(--kw-mut)}
@media print{.kw{display:none}}
</style>"""

JS = r"""(function(){
var D=__DATE__,REGEN=__REGEN__,API=REGEN.replace(/\/$/,''),JK='pb-kwjob-'+D,job=null,email='',codeStage=false,msg='',link='',busy=false,polling=false,root=document.getElementById('kw'),box=document.getElementById('kw-in'),data=null,K='pb-kw-'+D;
var KIND={wq:'Written question',ws:'Written statement',hd:'Debate',cm:'Committee',to:'Today'};
var st={on:{},own:[],off:{}};
try{var s=JSON.parse(localStorage.getItem(K)||'null');if(s){st=s;st.on=st.on||{};st.own=st.own||[];st.off=st.off||{}}}catch(x){}
try{job=JSON.parse(localStorage.getItem(JK)||'null')}catch(x){}
function save(){try{localStorage.setItem(K,JSON.stringify(st))}catch(x){}}
function el(t,a,txt){var n=document.createElement(t);if(a)for(var k in a){if(k==='cls')n.className=a[k];else n.setAttribute(k,a[k])}if(txt!=null)n.textContent=txt;return n}
function rx(term){var p=term.trim().split(/[\s\-]+/).filter(Boolean).map(function(x){return x.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')});
  if(!p.length)return null;try{return new RegExp('(?<![\\w-])'+p.join('[\\s\\-]*')+'(?![\\w])','i')}catch(x){return null}}
function active(){var t=[];data.suggestions.forEach(function(s){if(st.on[s.term])t.push(s.term)});return t.concat(st.own)}
function hay(i){return i.h+' '+i.x+' '+i.w}
function snippet(i,r){var t=i.x||'',m=r&&r.exec(t),p=el('p');if(!m){p.textContent=t.slice(0,220)+(t.length>220?'…':'');return p}
  var a=Math.max(0,m.index-110),b=Math.min(t.length,m.index+m[0].length+110);
  p.appendChild(document.createTextNode((a?'…':'')+t.slice(a,m.index)));p.appendChild(el('mark',null,m[0]));
  p.appendChild(document.createTextNode(t.slice(m.index+m[0].length,b)+(b<t.length?'…':'')));return p}
function chip(label,pressed,cls,onclick,why){var b=el('button',{type:'button',cls:'kw-chip'+(cls?' '+cls:''),'aria-pressed':String(!!pressed)});
  b.appendChild(document.createTextNode(label));b.addEventListener('click',onclick);
  if(why){b.title=why;b.addEventListener('mouseenter',function(){document.getElementById('kw-why').textContent=why});
    b.addEventListener('focus',function(){document.getElementById('kw-why').textContent=why})}return b}
function draw(){
  box.textContent='';
  var s1=el('div');s1.appendChild(el('h4',null,'Suggested for this edition'+(data.method==='ai'?' (picked by AI from the day’s material)':' (mined from the day’s material)')));
  var c1=el('div',{cls:'kw-chips'});
  data.suggestions.forEach(function(s){var lab=s.term+' ';var b=chip(lab,st.on[s.term],'',function(){st.on[s.term]=!st.on[s.term];save();draw()},s.why);
    b.appendChild(el('small',null,s.hits+(s.rising?' ↑':'')));c1.appendChild(b)});
  if(!data.suggestions.length)c1.appendChild(el('span',{cls:'kw-why'},'No suggestions for this edition.'));
  s1.appendChild(c1);s1.appendChild(el('p',{id:'kw-why',cls:'kw-why'},'Hover or focus a keyword to see why it was suggested. The number is how many items mention it; ↑ means rising.'));box.appendChild(s1);
  var s2=el('div');s2.appendChild(el('h4',null,'Your own keywords'));
  var f=el('form',{cls:'kw-add'}),inp=el('input',{type:'text',maxlength:'40','aria-label':'Add a keyword',placeholder:'Add a word or phrase, e.g. sovereign cloud'});
  f.appendChild(inp);f.appendChild(el('button',{type:'submit',cls:'kw-btn'},'Add'));
  f.addEventListener('submit',function(ev){ev.preventDefault();var v=inp.value.trim().replace(/\s+/g,' ');
    if(v&&v.length>1&&st.own.indexOf(v)<0&&st.own.length<10&&rx(v)){st.own.push(v);save();draw();var n=document.querySelector('.kw-add input');if(n)n.focus()}});
  s2.appendChild(f);var c2=el('div',{cls:'kw-chips'});c2.style.marginTop='6px';
  st.own.forEach(function(t){c2.appendChild(chip(t+' ✕',true,'',function(){st.own=st.own.filter(function(x){return x!==t});save();draw()},'Remove '+t))});
  s2.appendChild(c2);box.appendChild(s2);
  var s3=el('div');s3.appendChild(el('h4',null,'Standing topics (switch off what you don’t need today)'));var c3=el('div',{cls:'kw-chips'});
  data.topics.forEach(function(t){c3.appendChild(chip(t,!st.off[t],'kw-off',function(){st.off[t]=!st.off[t];if(!st.off[t])delete st.off[t];save();draw()}))});
  s3.appendChild(c3);box.appendChild(s3);
  // re-screen, in the browser
  var terms=active(),rs=terms.map(function(t){return {t:t,r:rx(t)}}).filter(function(x){return x.r});
  var hits=[],drop=[],per={};
  data.items.forEach(function(i){var h=hay(i),m=null;
    for(var j=0;j<rs.length;j++){if(rs[j].r.test(h)){m=m||rs[j];per[rs[j].t]=(per[rs[j].t]||0)+1}}
    if(m&&!i.b)hits.push({i:i,r:m.r});
    else if(!m&&(i.b||i.s)&&i.tp.length&&i.tp.every(function(t){return st.off[t]}))drop.push(i)});
  hits.sort(function(a,b){return (a.i.s-b.i.s)||(a.i.k<b.i.k?-1:1)});
  var missed=hits.filter(function(h){return !h.i.s}).length,droppedB=drop.filter(function(i){return i.b}).length;
  var sum=el('p',{cls:'kw-sum',role:'status'});
  sum.textContent=!terms.length&&!Object.keys(st.off).length?'Pick or add keywords to see what else today’s material holds. Nothing is spent until you ask for a rewrite.':
    (terms.length?'Your keywords find '+hits.length+' item'+(hits.length===1?'':'s')+' not in the briefing'+(missed?', '+missed+' of them missed by the standing rules':'')+'.':'')+
    (Object.keys(st.off).length?' Switching topics off would drop '+droppedB+' briefing item'+(droppedB===1?'':'s')+'.':'')+
    (data.fullCorpus?'':' This edition predates the full record, so only items the standing rules caught can be re-screened; a rewrite also searches debates for your own keywords.');
  box.appendChild(sum);
  if(hits.length){var ul=el('ul',{cls:'kw-res'});hits.slice(0,60).forEach(function(h){var i=h.i,li=el('li',{cls:i.s?'':'kw-new'});
      var a=i.l?el('a',{href:i.l,target:'_blank',rel:'noopener'},i.h):el('b',null,i.h);li.appendChild(a);
      li.appendChild(el('div',{cls:'kw-m'},[KIND[i.k],i.w,i.d,i.s?'':'missed by the standing rules'].filter(Boolean).join(' · ')));li.appendChild(snippet(i,h.r));ul.appendChild(li)});
    if(hits.length>60)ul.appendChild(el('li',{cls:'kw-m'},'and '+(hits.length-60)+' more; narrow your keywords to see them.'));box.appendChild(ul)}
  if(REGEN){var rg=el('div',{cls:'kw-regen'}),changed=terms.length||Object.keys(st.off).length;
    rg.appendChild(el('h4',null,'Rewrite the briefing with these keywords'));
    rg.appendChild(el('p',null,'An AI writer redrafts this edition around your keywords and topics. Rewrites are for approved readers: enter your email address. Most readers get one rewrite per edition, and each takes a few minutes.'));
    if(!job){var f2=el('form',{cls:'kw-add'}),em=el('input',{type:'email',required:'',autocomplete:'email','aria-label':'Your email address',placeholder:'Your email address'});
      em.value=email;var cd=el('input',{type:'password',autocomplete:'one-time-code',maxlength:'64','aria-label':'Your code',placeholder:'Your code'});
      var go=el('button',{type:'submit',cls:'kw-btn kw-main'},codeStage?'Rewrite with these keywords':'Continue');if(!changed||busy)go.disabled=true;
      f2.appendChild(em);if(codeStage)f2.appendChild(cd);f2.appendChild(go);
      function post(path,b){return fetch(API+path,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(b)}).then(function(r){return r.json().then(function(j){j._s=r.status;return j})})}
      function request(code){say('Starting…');return post('/api/request',{e:D,k:terms.slice(0,12),off:Object.keys(st.off),email:email,code:code}).then(function(j){busy=false;
          if(j.job&&j.key){job={job:j.job,key:j.key,k:terms.slice(0,12)};codeStage=false;try{localStorage.setItem(JK,JSON.stringify(job))}catch(x){}
            msg=j._s===200?'Started. Writing usually takes three to eight minutes; you can keep reading meanwhile.':(j.error||'')+' Here is the one you asked for.';draw();poll()}
          else{msg=j.error||'The rewrite could not be started.';draw()}})}
      f2.addEventListener('submit',function(ev){ev.preventDefault();if(busy)return;busy=true;go.disabled=true;
        var p;if(codeStage&&em.value.trim().toLowerCase()===email){p=request(cd.value.trim())}
        else{email=em.value.trim().toLowerCase();say('Checking…');p=post('/api/code',{email:email}).then(function(j){
          if(j.needCode===false)return request('');busy=false;
          if(j.sent||j.personal){codeStage=true;msg=j.personal?'Enter your access code.':'We have emailed a 6-digit code to '+email+'. Enter it here; it works for 10 minutes.';draw();var c=document.querySelector('.kw-regen input[autocomplete=one-time-code]');if(c)c.focus()}
          else{codeStage=false;msg=j.error||'The rewrite could not be started.';draw()}})}
        p.catch(function(){busy=false;msg='The rewrite service could not be reached. Please try again later.';draw()})});
      rg.appendChild(f2)}
    var rs=el('p',{id:'kw-rs',role:'status'},msg);rg.appendChild(rs);
    if(link){var a2=el('a',{href:link,target:'_blank',rel:'noopener'},'Open your rewritten briefing');rg.appendChild(a2);
      rg.appendChild(el('a',{cls:'kw-btn',href:mailto('Rewritten parliamentary briefing, '+D,'Here is a version of the parliamentary briefing for '+D+' rewritten around these keywords: '+(job.k||[]).join(', ')+'.\n\n'+link+'\n\nThe link works for 14 days.')},'Share by email'));
      var again=el('button',{type:'button',cls:'kw-btn'},'Start a new rewrite');again.addEventListener('click',function(){job=null;link='';msg='';try{localStorage.removeItem(JK)}catch(x){}draw()});rg.appendChild(again)}
    box.appendChild(rg);if(job&&!polling&&!link)poll()}
}
function mailto(sub,body){return 'mailto:?subject='+encodeURIComponent(sub)+'&body='+encodeURIComponent(body)}
function say(t){msg=t;var n=document.getElementById('kw-rs');if(n)n.textContent=t}
function poll(){if(!job)return;polling=true;
  fetch(API+'/api/job/'+encodeURIComponent(job.job)+'?key='+encodeURIComponent(job.key)).then(function(r){return r.json().then(function(j){j._s=r.status;return j})}).then(function(j){
    if(j._s===404){job=null;polling=false;try{localStorage.removeItem(JK)}catch(x){}say('');draw();return}
    if(j.status==='done'){polling=false;link=new URL('rewrite.html#j='+encodeURIComponent(job.job)+'&k='+encodeURIComponent(job.key),location.href).href;msg='Your rewrite is ready'+(j.title?': '+j.title:'')+'.';draw();return}
    if(j.status==='failed'){polling=false;job=null;try{localStorage.removeItem(JK)}catch(x){}msg=(j.error||'The rewrite failed.')+' Your rewrite has not been used up, so you can try again.';draw();return}
    say(j.status==='running'?'Writing your briefing… This usually takes three to eight minutes.':'Waiting for a writer to start…');setTimeout(poll,10000)})
  .catch(function(){say('Lost contact with the rewrite service; retrying…');setTimeout(poll,20000)})}
root.addEventListener('toggle',function(){if(!root.open||data)return;box.textContent='Loading the day’s material…';
  fetch('kw/'+D+'.json').then(function(r){if(!r.ok)throw 0;return r.json()}).then(function(j){data=j;
    data.suggestions.forEach(function(s){if(!(s.term in st.on))st.on[s.term]=false});draw()})
  .catch(function(){box.textContent='The keyword data for this edition could not be loaded.'})});
})();"""


def panel(d: str, regen_url: str = "") -> str:
    js = JS.replace("__DATE__", json.dumps(d)).replace("__REGEN__", json.dumps(regen_url or ""))
    return (f'{CSS}<details class="kw" id="kw"><summary>Tune keywords <small>pick what matters to you and re-screen today’s material'
            f'{", then ask for one rewrite" if regen_url else ""}</small></summary><div class="kw-in" id="kw-in" aria-live="polite"></div></details>'
            f'<script>{js}</script>')


def payload_json(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


VIEWER_JS = r"""(function(){
var API=__REGEN__.replace(/\/$/,''),q={};location.hash.slice(1).split('&').forEach(function(p){var i=p.indexOf('=');if(i>0)q[p.slice(0,i)]=decodeURIComponent(p.slice(i+1))});
var f=document.getElementById('rw'),m=document.getElementById('rw-msg'),s=document.getElementById('rw-share');
if(!q.j||!q.k||!API){m.textContent='This link is not complete.';return}
s.href='mailto:?subject='+encodeURIComponent('Rewritten parliamentary briefing')+'&body='+encodeURIComponent('Here is a version of the parliamentary briefing rewritten around chosen keywords:\n\n'+location.href+'\n\nThe link works for 14 days.');
fetch(API+'/r/'+encodeURIComponent(q.j)+'?key='+encodeURIComponent(q.k)).then(function(r){return r.text().then(function(t){if(!r.ok)throw t;return t})})
.then(function(h){f.srcdoc=h;f.hidden=false;m.textContent='';var t=/<title>([^<]*)<\/title>/i.exec(h);if(t)document.title=t[1].replace(/&amp;/g,'&')})
.catch(function(t){m.textContent=(typeof t==='string'&&t.length<200&&t)||'This rewrite could not be loaded. It may have expired.'})})();"""


def viewer_html(regen_url: str) -> str:
    """rewrite.html: shows a finished rewrite on the briefing site itself, so readers and shared links only ever
    see this site's address. The job id and key travel in the #fragment, which browsers never send to a server."""
    js = VIEWER_JS.replace("__REGEN__", json.dumps(regen_url or ""))
    return ('<!DOCTYPE html><html lang="en-GB"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            '<meta name="robots" content="noindex,nofollow"><meta name="referrer" content="no-referrer"><title>Rewritten briefing</title>'
            '<style>html,body{margin:0;height:100%;font:15px/1.4 system-ui,sans-serif;background:#fff;color:#1d1d1f}'
            '.rw-bar{display:flex;gap:16px;align-items:center;padding:8px max(4vw,16px);border-bottom:1px solid #ddd;background:#f6f6f4}'
            '.rw-bar a{color:#0b5cad}#rw-msg{padding:24px max(4vw,16px)}#rw{border:0;width:100%;height:calc(100% - 42px);display:block}'
            '@media (prefers-color-scheme:dark){html,body{background:#161617;color:#eee}.rw-bar{background:#222;border-color:#333}.rw-bar a{color:#7fb4ff}}</style></head>'
            '<body><div class="rw-bar"><a href="./">All briefings</a><a id="rw-share" href="#">Share by email</a></div>'
            '<p id="rw-msg" role="status">Loading the rewrite…</p>'
            '<iframe id="rw" title="Rewritten briefing" hidden sandbox="allow-popups allow-popups-to-escape-sandbox"></iframe>'
            f'<script>{js}</script></body></html>')


__all__ = ["panel", "payload_json", "viewer_html", "e"]
