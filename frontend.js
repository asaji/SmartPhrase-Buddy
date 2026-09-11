import {Editor} from '@tiptap/core';
import StarterKit from '@tiptap/starter-kit';
import DOMPurify from 'dompurify';
import {diffWordsWithSpace} from 'diff';
const $=s=>document.querySelector(s), app=$('#app');
let editors=[],activeDraft=false,dirty=false,selected=new Set(),current=null,epoch=0;
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const safe=s=>DOMPurify.sanitize(s,{ALLOWED_TAGS:['p','br','div','h1','h2','h3','h4','strong','b','em','i','u','ul','ol','li','blockquote'],ALLOWED_ATTR:[]});
function text(html){const d=document.createElement('div');d.innerHTML=safe(html);d.querySelectorAll('li').forEach(x=>x.prepend('• '));d.querySelectorAll('br').forEach(x=>x.replaceWith('\n'));d.querySelectorAll('li').forEach(x=>x.append('\n'));
 // A short "Label:" (<=2 words, e.g. Procedure/Anesthesia/Antibiotics) stays tight
 // to its neighbors, like Epic's own header block. A longer label (e.g. "Indication
 // for Procedure:") is treated as a section heading and always gets blank-line
 // spacing. A bare short label (nothing after the colon on its own line) also stays
 // tight against the plain-text line(s) that follow it, since those are its value
 // (e.g. "Procedure:" + the CPT line(s)) — that chain continues through further
 // unlabeled lines until the next label/heading closes it.
 const blocks=[...d.querySelectorAll('p,div,h1,h2,h3,h4,blockquote,ul,ol')];
 let chain=false;
 const compact=blocks.map(el=>{
  const isP=el.tagName==='P';
  const t=isP?el.textContent.trim():'';
  const m=isP?t.match(LABEL_LINE):null;
  const words=m?m[0].replace(/:\s*$/,'').trim().split(/\s+/).filter(Boolean).length:null;
  const isShortLabel=words!==null&&words<=2;
  const isList=isP&&LIST_LINE.test(el.textContent);
  const bare=m&&t===m[0].trim();
  const c=isShortLabel||isList||(isP&&words===null&&chain);
  chain=c&&(isShortLabel?bare:true);
  return c;
 });
 blocks.forEach((el,i)=>{el.append(blocks[i+1]&&compact[i]&&compact[i+1]?'\n':'\n\n');});
 return d.textContent.replace(/\n{3,}/g,'\n\n').trim();}
function tokenSet(html){return (text(html).match(/@[^@\s<>]+@|\{[^{}]*\}|\*{3,}/g)||[]).sort().join('\n');}
function notify(s){$('#notice').textContent=s;}
async function api(path,method='GET',body){const csrf=document.cookie.split('; ').find(x=>x.startsWith('csrftoken='))?.split('=')[1];const r=await fetch('/api/'+path,{method,headers:{'Content-Type':'application/json','X-CSRFToken':csrf||''},body:body===undefined?undefined:JSON.stringify(body),cache:'no-store'});if(r.status===401){notify('Session expired. Your draft remains here; sign in in another tab, then retry.');throw Error('Login required.');}const result=await r.json();if(!r.ok)throw Error(result.error||'Request failed.');return result;}
function action(selector,fn,enabled=()=>true){$(selector).addEventListener('click',async e=>{const b=e.currentTarget;b.disabled=true;try{await fn(e);}catch(err){notify(err.message);}finally{b.disabled=!enabled();}});}
function leave(){return !(activeDraft||dirty)||confirm('Discard your unsaved work? Temporary case drafts cannot be recovered.');}
function page(html){editors.forEach(e=>e.destroy());editors=[];epoch++;app.innerHTML=html;notify('');}
function rich(id,content='',onChange=()=>{dirty=true;}){const host=$(id);host.innerHTML='<div class="toolbar"></div><div class="surface"></div>';const e=new Editor({element:host.querySelector('.surface'),extensions:[StarterKit.configure({link:false,codeBlock:false,code:false,horizontalRule:false,heading:{levels:[1,2,3,4]}})],content:safe(content),injectCSS:false,onUpdate:onChange,editorProps:{transformPastedHTML:safe}});const commands=[['Bold',()=>e.chain().focus().toggleBold().run()],['Italic',()=>e.chain().focus().toggleItalic().run()],['Heading',()=>e.chain().focus().toggleHeading({level:2}).run()],['Bullets',()=>e.chain().focus().toggleBulletList().run()],['Numbers',()=>e.chain().focus().toggleOrderedList().run()],['Undo',()=>e.chain().focus().undo().run()],['Redo',()=>e.chain().focus().redo().run()]];commands.forEach(([label,fn])=>{const b=document.createElement('button');b.textContent=label;b.type='button';b.onmousedown=e=>e.preventDefault();b.onclick=fn;host.querySelector('.toolbar').append(b);});editors.push(e);return e;}
async function copy(html,formatted){html=reflowWrapped(html);if(formatted){await navigator.clipboard.write([new ClipboardItem({'text/html':new Blob([safe(html)],{type:'text/html'}),'text/plain':new Blob([text(html)],{type:'text/plain'})})]);}else await navigator.clipboard.writeText(text(html));notify('Copied. Review the pasted text in Epic; token activation is unverified.');}
function copyControls(get){action('#copy-plain',()=>copy(get(),false));action('#copy-rich',()=>copy(get(),true));wirePreviewCopy(get);}
function copyButtons(){return '<button id="copy-plain" class="primary">Copy plain text</button><button id="copy-rich">Copy formatted</button>'+previewButton();}
// Shows exactly what Copy plain text will produce — the same reflow + spacing
// rules that actually run at copy time — so the editor isn't a black box about
// which lines will end up tight vs. blank-line separated.
function previewButton(){return '<button id="preview-copy" type="button">Preview Epic paste</button>';}
function previewBody(){return '<pre id="preview-copy-body" class="diff" hidden></pre>';}
function wirePreviewToggle(refresh){const btn=$('#preview-copy'),body=$('#preview-copy-body');if(!btn||!body)return;
 btn.onclick=()=>{body.hidden=!body.hidden;btn.textContent=body.hidden?'Preview Epic paste':'Hide Epic paste preview';if(!body.hidden)refresh();};}
// Static content (a saved revision shown read-only) — nothing to observe.
function wirePreviewCopy(get){wirePreviewToggle(()=>{const body=$('#preview-copy-body');if(body)body.textContent=text(reflowWrapped(get()));});}
// A live Tiptap editor — a MutationObserver catches every content change,
// typed or programmatic (commands.setContent doesn't fire onUpdate here),
// so the preview never goes stale while it's open.
function wirePreviewEditor(editor){const refresh=()=>{const body=$('#preview-copy-body');if(body&&!body.hidden)body.textContent=text(reflowWrapped(editor.getHTML()));};
 wirePreviewToggle(refresh);
 new MutationObserver(refresh).observe(editor.view.dom,{childList:true,subtree:true,characterData:true});}
async function library(){activeDraft=false;dirty=false;current=null;page(`<div class="intro"><div><div class="eyebrow">YOUR WORDS, READY TO USE</div><h1>SmartPhrase library</h1><p>Find a phrase. Make it yours. Copy with confidence.</p></div><button id="new" class="primary">+ New phrase</button></div><div id="pending-banner"></div><div class="layout"><aside><input id="search" aria-label="Search library" placeholder="Search phrases, aliases, or content…"><div class="filters"><select id="kind" aria-label="Type"><option value="">All types</option><option value="clinic">Clinic counseling</option><option value="operative">Operative templates</option><option value="procedure">Procedure notes</option><option value="library">Library items</option><option value="other">Other notes</option></select><select id="favorites" aria-label="Favorites"><option value="">All phrases</option><option value="1">Favorites</option></select><input id="tag" aria-label="Tag filter" placeholder="Filter by exact tag"></div><small id="count"></small><div id="items"></div><div class="selected-bar"><button id="batch" class="full">Update selected masters (0)</button></div></aside><section class="panel" id="preview"><div class="empty">Select a phrase to preview and copy.<br>Start with your own text or a synthetic example.</div></section></div>`);
 action('#new',()=>master());action('#batch',()=>{if(!selected.size)throw Error('Select at least one template.');return batch();});let request=0;
 async function refresh(){let mine=++request;const result=await api('templates/?'+new URLSearchParams({q:$('#search').value,kind:$('#kind').value,tag:$('#tag').value,favorite:$('#favorites').value}));if(mine!==request||!$('#items'))return;$('#count').textContent=result.items.length+' phrases';
 {const pb=$('#pending-banner');if(pb){pb.innerHTML=result.pending_imports?`<button id="go-import" class="full">${result.pending_imports} phrase${result.pending_imports>1?'s':''} waiting in the import queue — review</button>`:'';if($('#go-import'))$('#go-import').onclick=()=>imports().catch(e=>notify(e.message));}}$('#items').innerHTML=result.items.map(t=>`<div class="item"><input type="checkbox" aria-label="Select ${esc(t.title)}" data-select="${t.id}" ${selected.has(t.id)?'checked':''}><button data-open="${t.id}"><strong>${t.favorite?'★ ':''}${esc(t.title)}</strong><small>${esc(t.epic_name||t.kind)}</small><span>${t.tags.map(x=>`<span class="badge">${esc(x)}</span>`).join('')}</span></button></div>`).join('')||'<div class="empty">No phrases found.</div>';document.querySelectorAll('[data-select]').forEach(c=>c.onchange=()=>{c.checked?selected.add(+c.dataset.select):selected.delete(+c.dataset.select);$('#batch').textContent=`Update selected masters (${selected.size})`;});document.querySelectorAll('[data-open]').forEach(b=>b.onclick=()=>preview(+b.dataset.open).catch(e=>notify(e.message)));}
 ['#search','#kind','#tag','#favorites'].forEach(s=>$(s).addEventListener('input',()=>refresh().catch(e=>notify(e.message))));await refresh();}
async function preview(id){const t=await api(`templates/${id}/`);current=t;$('#preview').innerHTML=`<div class="preview-top"><div><div class="eyebrow">${esc(t.kind)} · REVISION ${t.version}</div><h2>${esc(t.title)}</h2><small>${esc(t.epic_name)}</small></div><button id="favorite">${t.favorite?'★ Favorited':'☆ Favorite'}</button></div><div class="document">${safe(t.content)}</div>${t.header?'<small>Epic header is stored separately and excluded from these copy controls.</small>':''}<div class="actions">${copyButtons()}</div>${previewBody()}<hr class="divider"><div class="actions"><button id="edit">Edit master</button>${t.kind==='operative'?'<button id="case">Customize this case</button>':t.kind==='procedure'?'<button id="case">Fill out this procedure</button>':''}${t.case_draft&&(t.kind==='operative'||t.kind==='procedure')?`<button id="case-resume" class="primary">Resume saved case — saved ${new Date(t.case_draft.updated_at).toLocaleString()}${t.case_draft.stale_base?' (master changed since)':''}</button>`:''}</div><p class="muted">Updated ${new Date(t.updated_at).toLocaleString()} · ${t.revisions.length} revisions</p>`;copyControls(()=>t.content);action('#edit',()=>master(t));if($('#case'))action('#case',()=>(t.kind==='procedure'?procedureEditor:caseEditor)(t));if($('#case-resume'))action('#case-resume',async()=>{const d=await api(`drafts/${t.case_draft.id}/`);return (t.kind==='procedure'?procedureEditor:caseEditor)(t,d);});action('#favorite',async()=>{await api(`templates/${id}/`,'PUT',{...t,favorite:!t.favorite});await preview(id);});}
async function master(t=null,seg=null){const fresh=!t;page(`<div class="intro"><div><div class="eyebrow">${fresh?(seg?'IMPORT FROM PDF · UNAPPROVED':'NEW PHRASE'):'EDITING REUSABLE MASTER'}</div><h1>${fresh?(seg?('Import “'+esc(seg.name||'unnamed phrase')+'”'):'Add to your library'):esc(t.title)}</h1><p>Saving creates a permanent master revision.</p></div><button id="cancel">${seg?'Back to import queue':'Back to library'}</button></div><div class="editor-grid"><section class="panel"><div class="meta"><div><label for="title">Title</label><input id="title" value="${esc(t?.title||'')}"><small class="hint">A name you recognize at a glance when searching — not the Epic token.</small></div><div><label for="epic">Epic SmartPhrase name</label><input id="epic" value="${esc(t?.epic_name||'')}"><small class="hint">The Epic .phrase this came from, e.g. ASOPNSPRALP. Optional; also searched.</small></div><div><label for="type">Type</label><select id="type"><option value="clinic">Clinic counseling</option><option value="operative">Operative template</option><option value="procedure">Procedure note</option><option value="library">Library item</option><option value="other">Other note</option></select><small class="hint">Routes the phrase to its own workflow. <strong>Operative</strong> → case-checklist editor; add <code>[[ … ]]</code> markers (e.g. <code>[[Extent: RALP without pelvic lymphadenectomy | RALP with standard pelvic lymphadenectomy | RALP with extended pelvic lymphadenectomy]]</code>) anywhere a fixed set of options should be picked instead of typed, alongside the AI checklist for everything else. Declare a variable&#39;s options once; reuse the same choice anywhere else in the note by writing just <code>[[Extent]]</code> — you pick it once and every occurrence is filled. <strong>Procedure note</strong> (office cysto, biopsy) → checkbox editor; add <code>[[Bladder: normal | trabeculation | mass]]</code> or <code>[[EBL: minimal | *** mL]]</code> markers where findings should be picked, then <code>[[Bladder]]</code> to repeat a choice. <strong>Library item</strong> (risks/benefits/evidence) → master editor for now.</small></div><div><label for="tags">Tags</label><input id="tags" value="${esc(t?.tags.join(', ')||'')}"><small class="hint">Comma-separated labels to filter by, e.g. prostate, robotic, counseling.</small></div></div><label for="aliases">Search aliases</label><input id="aliases" value="${esc(t?.aliases.join(', ')||'')}"><small class="hint">Extra words that should surface this phrase in search — abbreviations and synonyms, e.g. TP, TR, RALP, radical prostatectomy.</small><label>Reusable content / operative narrative</label><small class="hint">The body Epic inserts for this SmartPhrase. For an operative template, keep only Date of Procedure and Patient/MRN in the Epic header box on the right — everything from “Surgeon:” onward stays here and is fully editable.</small><div id="content"></div><div id="fixed-warning"></div><small class="hint" id="shared-ref"></small><div class="actions"><button id="reflow" type="button">Reflow wrapped lines</button>${previewButton()}</div>${previewBody()}<small class="hint">Merges paragraphs that were split at the Epic PDF export&#39;s hard word-wrap back into flowing text. Keeps <code>Label:</code> lines, lists, <code>[[ … ]]</code> markers and blank-line breaks. Review the result, then save a new revision.</small><small class="hint">Preview shows exactly what Copy plain text will produce, including which lines stay tight and which get section spacing — see Settings → Copy &amp; paste formatting for the full rules.</small>${fresh?'':'<details id="improve"><summary>Ask AI to improve this note — optional, reviewed diff</summary><p class="muted">Describe what should read better — clarity, flow, redundancy, structure, consistent tense. The AI works only from what is already written here; it will not invent findings, change meaning, or touch a heading. You review a full diff before anything is applied, and it still is not saved until you confirm below and save a new revision.</p><label for="improve-instructions">Instructions</label><textarea id="improve-instructions" placeholder="e.g. tighten the wording and remove redundant phrases without changing any clinical content"></textarea><button id="improve" type="button">Propose improvement</button></details>'}<label><input type="checkbox" id="confirm-master"> I reviewed reusable content, fixed values, and the operative boundary.</label><button id="save" class="primary">${fresh?'Approve and save to library':'Save new master revision'}</button></section><aside class="panel">${fresh?'<h2>Source</h2><p class="muted">Paste or edit the source here, then transfer it into the narrative. The original source text is preserved when you save.</p><div id="source"></div><div class="actions"><button id="transfer">Use pasted source</button><button id="demo">Load synthetic example</button></div>':'<h2>Source & revisions</h2>'}<h3>Epic header boundary</h3><p class="muted">Epic imports only Date of Procedure and Patient/MRN. Keep just those two lines in the excluded header; everything from “Surgeon:” down stays in the editable narrative (so the AI can improve the whole note, and modifier-22 statements can sit above the indication). The header never enters case AI requests or narrative copying.</p><div class="actions"><button id="split">Split after Patient/MRN</button><button id="split-indication">Split at Indication for Procedure</button></div><label>Generic Epic header (excluded)</label><div class="short" id="header"></div><details><summary>Preserved original source</summary><pre id="original"></pre></details>${fresh?'':'<h3>Revision history</h3><div id="history"></div><button id="delete" class="danger">Delete master and history</button>'}</aside></div><div id="reviews"></div>`);
 const mine=epoch;$('#type').value=t?.kind||'clinic';let original=t?.original_source||'',pendingId=null,graded=false;$('#original').textContent=original;
 const st=await api('status/').catch(()=>({}));if(epoch!==mine)return;const aiReady=!!st.configured;
 const sharedMap=new Map((st.shared_choices||[]).map(c=>[c.label.toLowerCase(),c.options]));
 $('#shared-ref').innerHTML=(st.shared_choices||[]).length?'Shared choice variables (reference as <code>[[@Name]]</code>, manage in Settings): '+(st.shared_choices||[]).map(c=>esc('@'+c.label)).join(', ')+'.':'';
 const content=rich('#content',t?.content||'',()=>{dirty=true;graded=false;fixed();}), header=rich('#header',t?.header||'');
 wirePreviewEditor(content);
 function fixed(){const w=[];
  if(/\b\d{1,3}[ -](year|yr)[ -]old\b/i.test(content.getText()))w.push('Fixed patient age found. Review reusable content before saving.');
  markerVariables(content.getHTML(),sharedMap).forEach(v=>{
   if(v.missing)w.push('“[[@'+v.label+']]” refers to a shared choice variable that does not exist — create “'+v.label+'” in Settings, or write [['+v.label+': option | option]] here instead.');
   else if(v.source==='shared'){/* resolved from Settings — no warning */}
   else if(v.mixed)w.push('Choice variable “'+v.label+'” is declared locally and also referenced as [[@'+v.label+']] — the local list is used; drop the @ or the local declaration.');
   else if(!v.declared)w.push('Choice variable “'+v.label+'” is used'+(v.idxs.length>1?' '+v.idxs.length+' times':'')+' but never declared with options — write [['+v.label+': option | option]] at its first use, then [['+v.label+']] elsewhere.');
   else if(v.conflict)w.push('Choice variable “'+v.label+'” is declared more than once with different option lists — the first list is used; change the later ones to [['+v.label+']].');});
  $('#fixed-warning').innerHTML=w.map(x=>`<p class="warning">${esc(x)}</p>`).join('');}fixed();
 if(fresh){const source=rich('#source');let pastedOriginal='';
  $('#source').addEventListener('paste',event=>{pastedOriginal=event.clipboardData?.getData('text/html')||event.clipboardData?.getData('text/plain')||'';pendingId=null;});
  action('#transfer',()=>{original=pastedOriginal||source.getHTML();content.commands.setContent(source.getHTML());$('#original').textContent=original;dirty=true;fixed();});
  action('#demo',()=>{source.commands.setContent('<p>SYNTHETIC EXAMPLE — NOT A CLINICAL TEMPLATE</p><p>Patient: @NAME@ · @MRN@</p><h2>Indication for Procedure</h2><p>@AGE@ with indication ***.</p><h2>Operative Description</h2><p>The planned dissection was performed. Assistant: {ASROBOASSIST:165493}. No complications.</p>');$('#title').value='Synthetic operative example';$('#epic').value='SYNTHETIC_DEMO';$('#type').value='operative';pendingId=null;});
  if(seg){const h=safe(seg.html);source.commands.setContent(h);content.commands.setContent(h);original=seg.text;$('#original').textContent=original;pastedOriginal=seg.text;pendingId=seg.id;if(seg.name){$('#epic').value=seg.name;$('#title').value=seg.name;}dirty=true;fixed();notify('Loaded from the queue. Set the type, split the Epic header if needed, review, then approve.'+(seg.flags&&seg.flags.length?' — flags: '+seg.flags.join(' '):''));}}
 function splitAt(re,label){const d=document.createElement('div');d.innerHTML=content.getHTML();const nodes=[...d.childNodes];const index=nodes.findIndex(n=>re.test((n.textContent||'').trim()));if(index<0)throw Error('“'+label+'” was not found at a line boundary. Move the lines between the two editors by hand.');header.commands.setContent(nodes.slice(0,index).map(n=>n.outerHTML||esc(n.textContent)).join(''));content.commands.setContent(nodes.slice(index).map(n=>n.outerHTML||esc(n.textContent)).join(''));dirty=true;notify('Split done — check that only Date and Patient/MRN are in the header box.');}
 action('#split',()=>splitAt(/^(surgeon|attending)\b/i,'Surgeon:'));
 action('#split-indication',()=>splitAt(/^indication for procedure/i,'Indication for Procedure'));
 action('#reflow',()=>{const before=content.getHTML(),after=reflowWrapped(before);
  if(after===before){notify('Nothing to reflow — no hard-wrapped paragraph fragments found.');return;}
  if(!confirm('Merge paragraphs that were split at the Epic PDF export’s hard word-wrap into flowing text? Label lines, lists, [[ … ]] markers and blank-line breaks are kept. Review the result and save a new revision; editor undo reverts it.'))return;
  content.commands.setContent(safe(after));dirty=true;graded=false;fixed();
  notify('Wrapped lines merged. Review the narrative, then save a new master revision.');});
 if(!fresh)action('#improve',async()=>{
  const instruction=$('#improve-instructions').value.trim();
  if(!instruction)throw Error('Describe what you want improved.');
  const source=content.getHTML();
  const result=await api('propose/','POST',{mode:'master',ids:[t.id],content:source,instruction});
  if(epoch!==mine)return;
  $('#reviews').innerHTML='';showProvider(result.provider);
  reviewCard($('#reviews'),result.proposals[0],async html=>{
   if(content.getHTML()!==source)throw Error('The narrative changed after this proposal. Reject and request a new one to keep your edits.');
   guardHeadings(source,html);content.commands.setContent(html);dirty=true;graded=false;fixed();
   notify('Improvement applied to the editor. Review it, then save a new master revision.');
  });
 });
 app.querySelectorAll('input,select').forEach(el=>el.addEventListener('input',()=>dirty=true));
 action('#cancel',()=>{if(leave())return seg?imports():library();});
 async function doSave(){let html=content.getHTML();if(t&&tokenSet(t.content+t.header)!==tokenSet(html+header.getHTML())&&!confirm('Protected Epic tokens changed. Have you explicitly reviewed these additions/removals?'))return;const data={title:$('#title').value,epic_name:$('#epic').value,kind:$('#type').value,tags:$('#tags').value.split(',').map(x=>x.trim()).filter(Boolean),aliases:$('#aliases').value.split(',').map(x=>x.trim()).filter(Boolean),content:html,header:header.getHTML(),original_source:original||html,favorite:t?.favorite||false,version:t?.version,pending_import_id:fresh?pendingId:null};const saved=await api(fresh?'templates/':`templates/${t.id}/`,fresh?'POST':'PUT',data);const queued=fresh&&pendingId;pendingId=null;dirty=false;if(seg){await imports();notify('Saved “'+saved.title+'” as revision '+saved.version+(queued?'. Removed from the import queue.':'.'));}else{await library();await preview(saved.id);notify('Master saved as revision '+saved.version+'.');}}
 action('#save',async()=>{if(!$('#confirm-master').checked)throw Error('Review content and confirm the checkbox before saving.');
  if(!aiReady||graded){await doSave();return;}
  notify('Running a grammar & punctuation check before saving…');
  const source=content.getHTML();let r;try{r=await api('grammar/','POST',{content:source});}catch(err){if(epoch!==mine)return;if(content.getHTML()===source)graded=true;notify(err.message+' Click save again to save without it.');return;}
  if(epoch!==mine)return;assertSource(content,source);
  graded=true;$('#reviews').innerHTML='';
  if(r.provider==='mock'){notify('MOCK provider — no grammar check performed. Saving.');await doSave();return;}
  if(r.proposal.content===content.getHTML()){notify('Grammar check: nothing to fix. Saving.');await doSave();return;}
  showProvider(r.provider);
  reviewCard($('#reviews'),r.proposal,async html=>{assertSource(content,source);content.commands.setContent(html);graded=true;await doSave();});
  const skip=document.createElement('button');skip.type='button';skip.textContent='Save without these fixes';skip.onclick=async()=>{$('#reviews').innerHTML='';await doSave();};
  $('#reviews').querySelector('.review .actions')?.append(skip);
 });
 if(t){$('#history').innerHTML=t.revisions.map(r=>`<details><summary>Revision ${r.version} · ${new Date(r.created_at).toLocaleString()}</summary><div class="document">${safe(r.snapshot.content)}</div><button data-restore="${r.version}">Restore as new revision</button></details>`).join('');document.querySelectorAll('[data-restore]').forEach(b=>b.onclick=async()=>{try{if(!confirm('Restore this revision? Unsaved edits will be discarded.'))return;await api(`templates/${t.id}/restore/`,'POST',{version:t.version,restore_version:+b.dataset.restore});dirty=false;await master(await api(`templates/${t.id}/`));notify('Revision restored as a new revision.');}catch(e){notify(e.message);}});action('#delete',async()=>{if(confirm('Permanently delete this master and all its revisions? Export a backup first if needed.')){await api(`templates/${t.id}/`,'DELETE');selected.delete(t.id);await library();}});}
}
async function imports(){activeDraft=false;dirty=false;current=null;let showSkipped=false,counts={};
 page(`<div class="intro"><div><div class="eyebrow">FROM YOUR EPIC PDF EXPORT</div><h1>Import queue</h1><p>Pick a phrase to review and add to your library. Skip the ones you don't need.</p></div><button id="back">Back to library</button></div><section class="panel"><div id="q-summary" class="muted"></div><div class="actions"><label class="filelabel">Upload a PDF export<input type="file" id="pdf" accept="application/pdf,.pdf" aria-label="Epic SmartPhrase PDF export"></label><button type="button" id="toggle-skipped" hidden></button><button type="button" id="skip-all" hidden></button><button type="button" id="clear-resolved" hidden>Clear imported &amp; skipped</button></div><p class="hint">The PDF is parsed in your browser session and not stored. Extracted phrase text stays in your private queue until you import or clear it. Re-uploading the same PDF adds nothing.</p><div id="q-list"></div></section>`);
 action('#back',()=>{if(leave())return library();});
 function render(data){const items=data.items,c=data.counts;counts=c;
  $('#q-summary').textContent=(c.pending||c.imported||c.dismissed)?`${c.pending} awaiting review · ${c.imported} imported · ${c.dismissed} skipped${showSkipped?' — showing skipped':''}`:'Your import queue is empty. Upload an Epic “print SmartPhrases” PDF to fill it.';
  $('#q-list').innerHTML=items.map(s=>`<div class="qrow"><button class="qopen" data-open="${s.id}"><strong>${esc(s.name||'(unnamed phrase)')}</strong><small>${s.chars} chars${s.source_name?' · '+esc(s.source_name):''}${s.flags&&s.flags.length?' · '+s.flags.length+' flag'+(s.flags.length>1?'s':''):''}</small></button><div class="qact">${showSkipped?`<button data-restore="${s.id}">Restore</button>`:`<button data-skip="${s.id}">Skip</button>`}</div></div>`).join('')||`<div class="empty">${showSkipped?'Nothing skipped.':'Queue is clear — nothing left to import.'}</div>`;
  $('#q-list').querySelectorAll('[data-open]').forEach(b=>b.onclick=()=>{const s=items.find(x=>x.id==b.dataset.open);master(null,s).catch(e=>notify(e.message));});
  $('#q-list').querySelectorAll('[data-skip]').forEach(b=>b.onclick=()=>resolve(b.dataset.skip,'dismiss'));
  $('#q-list').querySelectorAll('[data-restore]').forEach(b=>b.onclick=()=>resolve(b.dataset.restore,'restore'));
  const tg=$('#toggle-skipped');tg.hidden=!(c.dismissed||showSkipped);tg.textContent=showSkipped?'Hide skipped':`Show skipped (${c.dismissed})`;
  const sa=$('#skip-all');
  if(showSkipped){sa.hidden=!c.dismissed;sa.textContent=`Restore all (${c.dismissed})`;}
  else{sa.hidden=!c.pending;sa.textContent=`Skip all (${c.pending})`;}
  $('#clear-resolved').hidden=!(c.imported||c.dismissed);}
 async function reload(){try{render(await api('imports/'+(showSkipped?'?dismissed=1':'')));}catch(e){notify(e.message);}}
 async function resolve(id,act){try{await api('imports/'+id+'/resolve/','POST',{action:act});await reload();}catch(e){notify(e.message);}}
 action('#toggle-skipped',async()=>{showSkipped=!showSkipped;await reload();});
 action('#skip-all',async()=>{const restoring=showSkipped,n=restoring?counts.dismissed:counts.pending;
  if(!n)return;
  if(!confirm(restoring?`Restore all ${n} skipped phrase${n>1?'s':''} back to the review list?`:`Skip all ${n} phrase${n>1?'s':''} awaiting review? They move to the skipped list and can be restored.`))return;
  const r=await api('imports/resolve-all/','POST',{action:restoring?'restore':'dismiss'});
  if(restoring)showSkipped=false;
  notify((restoring?'Restored ':'Skipped ')+r.updated+' phrase'+(r.updated===1?'':'s')+'.');await reload();});
 action('#clear-resolved',async()=>{if(!confirm('Delete all imported and skipped queue entries? Templates you already saved are not affected.'))return;const r=await api('imports/clear/','POST',{scope:'resolved'});notify('Removed '+r.deleted+' queue entries.');showSkipped=false;await reload();});
 $('#pdf').addEventListener('change',async e=>{const file=e.target.files[0];if(!file)return;$('#q-list').textContent='Extracting…';try{
  if(file.size>25*1024*1024)throw Error('PDF exceeds the 25 MB import limit.');
  const csrf=document.cookie.split('; ').find(x=>x.startsWith('csrftoken='))?.split('=')[1];const fd=new FormData();fd.append('file',file);
  const r=await fetch('/api/import/pdf/',{method:'POST',headers:{'X-CSRFToken':csrf||''},body:fd,cache:'no-store'});
  const result=await r.json();if(!r.ok)throw Error(result.error||'Import failed.');
  notify(result.added+' phrase'+(result.added===1?'':'s')+' added to the queue'+(result.skipped?', '+result.skipped+' already in it':'')+'.');
  e.target.value='';showSkipped=false;await reload();
 }catch(err){notify(err.message);await reload();}});
 await reload();}
function showDiff(host,source,proposal){host.innerHTML=diffWordsWithSpace(text(source),text(proposal)).map(p=>p.added?`<ins>${esc(p.value)}</ins>`:p.removed?`<del>${esc(p.value)}</del>`:esc(p.value)).join('');}
function reviewCard(container,p,onAccept){const node=document.createElement('section');node.className='review';node.innerHTML=`<h3>Proposed revision</h3><p>${esc(p.summary)}</p><div class="warning">${[...p.questions,...p.warnings].map(x=>`<p>${esc(x)}</p>`).join('')}<p>Existing template assertions are not verified case facts.</p></div><div class="review-head"><strong>Proposed narrative</strong><span><ins>additions</ins> · <del>deletions</del></span><button type="button" class="toggle-clean">Show clean version</button></div><div class="diff document"></div><div class="token-warning"></div><details class="manual"><summary>Edit the proposed text before accepting</summary><div class="proposal-editor"></div></details><label><input type="checkbox" class="ack"> I reviewed the proposal, questions, defaults, and any protected token changes.</label><div class="actions"><button class="accept primary">Accept</button><button class="reject">Reject</button></div>`;container.append(node);let proposalEditor,clean=false;
 function refresh(){const html=proposalEditor.getHTML();const box=node.querySelector('.diff');if(clean){box.innerHTML=safe(html);}else{showDiff(box,p.source,html);}node.querySelector('.token-warning').innerHTML=tokenSet(p.source)!==tokenSet(html)?'<p class="warning">Protected Epic tokens changed. Review each addition/removal; optional passage removal requires explicit approval.</p>':'';node.querySelector('.ack').checked=false;}
 const id='proposal-'+Math.random().toString(36).slice(2);node.querySelector('.proposal-editor').id=id;proposalEditor=rich('#'+id,p.content,refresh);refresh();
 node.querySelector('.toggle-clean').onclick=e=>{clean=!clean;e.target.textContent=clean?'Show changes':'Show clean version';refresh();};
 node.querySelector('.reject').onclick=()=>{proposalEditor.destroy();node.remove();notify('Proposal rejected. Saved content unchanged.');};
 node.querySelector('.accept').onclick=async e=>{if(!node.querySelector('.ack').checked){notify('Explicit review is required before acceptance.');return;}e.target.disabled=true;try{await onAccept(proposalEditor.getHTML());proposalEditor.destroy();node.remove();}catch(err){notify(err.message);e.target.disabled=false;}};
}
const TOKEN_RX=/@[^@\s<>]+@|\{[^{}]*\}|\*{3,}/g;
function tokenCount(html){return (text(html).match(TOKEN_RX)||[]).length;}
// Field markers: [[Label: option | option | *** value]] declares a local choice list;
// [[Label]] elsewhere reuses it; [[@Label]] pulls its options from an account-level
// shared choice variable (managed in Settings) instead.
const MARK_RX=/\[\[[^\[\]]+?\]\]/g;
function markerParts(m){let c=m.slice(2,-2).trim();const shared=c.startsWith('@');if(shared)c=c.slice(1).trim();const ci=c.indexOf(':');return {label:(ci>=0?c.slice(0,ci):c).trim(),opts:(ci>=0?c.slice(ci+1):'').split('|').map(x=>x.trim()).filter(Boolean),shared};}
function markerList(html){const d=document.createElement('div');d.innerHTML=safe(html);const out=[];let i=0;textRuns(d).forEach(nodes=>{(nodes.map(n=>n.nodeValue).join('').match(MARK_RX)||[]).forEach(m=>{out.push({idx:i++,...markerParts(m),raw:m});});});return out;}
// One entry per distinct choice variable, keyed by its label (case-insensitive). The first
// occurrence that carries an option list declares the choices; every later [[Label]] — or a
// repeated [[Label: … ]] — is a reference filled from the same control. `idxs` are the marker
// positions (see markerList/fillMarkers) that share the value. `declared`: an option list was
// seen anywhere; `conflict`: a later occurrence declared a different list (the first wins).
// `sharedMap`: Map(lowercased label -> options[]) from GET /api/status/ .shared_choices.
// A variable resolves to a shared list only when it uses the explicit [[@Label]] form
// AND is never declared locally — a plain bare [[Label]] is unaffected. `source==='shared'`
// when resolved from the map; `missing` when [[@Label]] names no shared variable; `mixed`
// when both [[@Label]] and a local [[Label: … ]] appear (the local list wins).
function markerVariables(html,sharedMap){const vars=new Map();
 markerList(html).forEach(m=>{const key=m.label.trim().toLowerCase();
  let v=vars.get(key);
  if(!v){v={key,label:m.label.trim()||'Field',opts:[],declared:false,conflict:false,sharedRef:false,idxs:[]};vars.set(key,v);}
  v.idxs.push(m.idx);
  if(m.shared)v.sharedRef=true;
  if(m.opts.length){if(!v.declared){v.opts=m.opts;v.declared=true;}
   else if(m.opts.join(' | ')!==v.opts.join(' | '))v.conflict=true;}});
 const sm=sharedMap||new Map();
 return [...vars.values()].map(v=>{
  if(v.sharedRef&&!v.declared){const opts=sm.get(v.key);
   if(opts&&opts.length){v.opts=opts.slice();v.declared=true;v.source='shared';}
   else v.missing=true;}
  else if(v.sharedRef&&v.declared)v.mixed=true;
  return v;});}
// Substitute chosen values. A marker that is the whole line becomes "Label: value." (label dropped
// if the value already leads with it); a marker inside a sentence is replaced with the value alone.
function fillMarkers(html,vals){const d=document.createElement('div');d.innerHTML=safe(html);let idx=0;
 textRuns(d).forEach(nodes=>{const raw=nodes.map(n=>n.nodeValue).join('');const matches=[...raw.matchAll(MARK_RX)];
  const bare=raw.replace(MARK_RX,'').replace(/[\s.;,:•·—–-]+/g,'')==='';
  const edits=[];matches.forEach(m=>{const here=idx++;if(!vals.has(here))return;
   let value=vals.get(here).trim();const {label}=markerParts(m[0]);
   if(bare){if(label&&!value.toLowerCase().startsWith(label.toLowerCase()))value=label+': '+value;
    if(!/[.!?]$/.test(value))value+='.';value=value.charAt(0).toUpperCase()+value.slice(1);}
   edits.push({start:m.index,end:m.index+m[0].length,value});});editRun(nodes,edits);});return d.innerHTML;}
// After an AI polish pass, force every [[ … ]] marker back to its exact authored text — a weak
// model sometimes rewords the options inside an unfilled marker. Positional, order preserved.
function restoreMarkers(base,after){const orig=text(base).match(MARK_RX)||[];if(!orig.length)return after;let i=0;return after.replace(MARK_RX,()=>i<orig.length?orig[i++]:'');}
const joinList=a=>a.length<2?(a[0]||''):a.slice(0,-1).join(', ')+' and '+a[a.length-1];
// Epic's PDF export hard-wraps prose at ~110 columns; import stores one <p> per wrapped
// fragment. Merge a run of <p> back into flowing paragraphs. A <p> never merges *into* the
// previous one when it starts a new block — empty (a section break), a "Label:" line, or a
// bulleted/numbered line. A fragment is joined to the previous paragraph only when that
// paragraph looks wrap-truncated: for a label line, its text does not end in . ? ! : ; ) ]
// and it is already >=88 chars (i.e. the value itself wrapped); for prose, it does not end
// in that punctuation, or it is already >=95 chars. [[ … ]] markers are plain text and
// survive; blank-line <p></p> separators are kept.
const LABEL_LINE=/^[A-Za-z][A-Za-z0-9 /()'’.-]{0,40}:(\s|$)/;
const LIST_LINE=/^\s*(?:[-*•·▪]|\(?\d+[.)])\s+/;
const PARA_END=/[.!?:;)\]]$/;
function reflowWrapped(html){
 const d=document.createElement('div');d.innerHTML=safe(html);
 const vis=el=>el.textContent.replace(/\s+/g,' ').trim();
 const startsNew=el=>el.tagName!=='P'||!vis(el)||LABEL_LINE.test(vis(el))||LIST_LINE.test(el.textContent);
 let prev=null;
 [...d.children].forEach(el=>{
  const canAbsorb=prev&&prev.tagName==='P'&&vis(prev)&&!LIST_LINE.test(prev.textContent);
  if(canAbsorb&&!startsNew(el)){
   const pt=vis(prev);
   const trunc=LABEL_LINE.test(pt)?(!PARA_END.test(pt)&&pt.length>=88):(!PARA_END.test(pt)||pt.length>=95);
   if(trunc){
    prev.append(document.createTextNode(' '));
    while(el.firstChild)prev.append(el.firstChild);
    el.remove();return;
   }
  }
  prev=el;
 });
 return d.innerHTML;
}
function headings(h){const d=document.createElement('div');d.innerHTML=safe(h);return [...d.querySelectorAll('h1,h2,h3,h4')].map(x=>x.textContent.trim().toLowerCase()).filter(Boolean);}
function guardHeadings(before,after){const lost=headings(before).filter(x=>!headings(after).includes(x));if(lost.length&&!confirm('The proposed text no longer has this heading: “'+lost.join('”, “')+'”. That usually means a whole section was removed. Apply anyway?'))throw Error('Not applied — reject this proposal and rerun to keep the section.');}
function guardShrink(before,after){guardHeadings(before,after);
 const bl=h=>{const d=document.createElement('div');d.innerHTML=safe(h);return blockList(d).filter(x=>x.textContent.trim()).length;};
 const bb=bl(before),ab=bl(after);
 if(ab<bb-1&&!confirm('The AI polish removed '+(bb-ab)+' lines/paragraphs from the filled note. That usually means content was deleted, not just tidied. Apply anyway?'))throw Error('Not applied — reject it, or fill the fields with the AI polish switched off.');
 const len=h=>text(h).replace(/\s+/g,' ').trim().length;
 if(len(after)<len(before)*0.7&&!confirm('The AI polish is much shorter than the filled note ('+len(before)+' → '+len(after)+' characters). Sentences may have been dropped. Apply anyway?'))throw Error('Not applied — reject it, or fill the fields with the AI polish switched off.');}
function assertSource(editor,source){if(editor.isDestroyed||editor.getHTML()!==source)throw Error('The narrative changed after this grammar request. Run the grammar check again to preserve your edits.');}
function blockList(root){return [...root.querySelectorAll('p,li,h1,h2,h3,h4,div,blockquote')].filter(b=>!b.querySelector('p,li,h1,h2,h3,h4,div,blockquote'));}
// Keep inline text together, including tokens split by bold/italic spans. Block
// boundaries and hard breaks separate runs, including text before nested lists.
function textRuns(root){const runs=[];let nodes=[];
 const flush=()=>{if(nodes.length)runs.push(nodes);nodes=[];};
 function visit(node){if(node.nodeType===Node.TEXT_NODE){nodes.push(node);return;}
  const boundary=/^(P|LI|H[1-4]|DIV|BLOCKQUOTE|UL|OL|BR)$/.test(node.nodeName);
  if(boundary)flush();node.childNodes.forEach(visit);if(boundary)flush();}
 root.childNodes.forEach(visit);flush();return runs;}
function editRun(nodes,edits){const positions=[];let offset=0;
 nodes.forEach(node=>{positions.push({node,start:offset,end:offset+node.length});offset+=node.length;});
 // Reverse order keeps original offsets valid. Edits must not overlap.
 edits.slice().sort((a,b)=>b.start-a.start).forEach(edit=>{
  const first=positions.find(p=>p.start<=edit.start&&p.end>edit.start);
  const last=positions.find(p=>p.start<edit.end&&p.end>=edit.end);
  if(!first||!last)return;
  const range=document.createRange();range.setStart(first.node,edit.start-first.start);range.setEnd(last.node,edit.end-last.start);
  range.deleteContents();if(edit.value)range.insertNode(document.createTextNode(edit.value));
 });}
function stripTokens(html,includeMarkers=false){const d=document.createElement('div');d.innerHTML=safe(html);
 const regex=includeMarkers?new RegExp(MARK_RX.source+'|'+TOKEN_RX.source,'g'):TOKEN_RX;
 textRuns(d).forEach(nodes=>{const value=nodes.map(n=>n.nodeValue).join('');editRun(nodes,[...value.matchAll(regex)].map(m=>({start:m.index,end:m.index+m[0].length,value:''})));});return d.innerHTML;}
// Resolve removals first so deleting a sentence wins over every fill inside it.
const SENT=/[.!?\n]/;
function applyFills(html,subs,removeIdx){const d=document.createElement('div');d.innerHTML=safe(html);let idx=0;
 textRuns(d).forEach(nodes=>{const value=nodes.map(n=>n.nodeValue).join('');
  const matches=[...value.matchAll(TOKEN_RX)].map(m=>({start:m.index,end:m.index+m[0].length,idx:idx++}));
  const removals=[];
  matches.filter(m=>removeIdx.has(m.idx)).forEach(m=>{let start=m.start,end=m.end;
   while(start>0&&!SENT.test(value[start-1]))start--;
   while(end<value.length&&!SENT.test(value[end]))end++;if(end<value.length)end++;
   const prev=removals.at(-1);if(prev&&start<=prev.end)prev.end=Math.max(prev.end,end);else removals.push({start,end,value:''});});
  const fills=matches.filter(m=>subs.has(m.idx)&&!removals.some(r=>m.start<r.end&&m.end>r.start)).map(m=>({...m,value:subs.get(m.idx)}));
  editRun(nodes,[...removals,...fills]);});
 blockList(d).forEach(b=>{if(!b.textContent.trim())b.remove();});return d.innerHTML;}
// Opt-in "save this case to my account" — one resumable server copy per master
// template. Only the current working narrative is sent; no AI output, instructions
// or draft-history checkpoints. `acct.id` tracks the row saved/resumed this session
// so Finish and clear can offer to delete it. See README privacy boundary.
function accountControls(t,getHtml,labelSel,btnSel,acct){
 action(btnSel,async()=>{
  const label=($(labelSel)?.value||'').trim();
  const d=await api('drafts/','POST',{template_id:t.id,content:getHtml(),label});
  acct.id=d.id;
  notify('Saved to your account. Resume it from any device within 7 days'+(d.stale_base?' — the master template has changed since.':'.'));
 });
}
async function finishAndClear(acct){
 if(!confirm('Finish and permanently clear this temporary draft, including its draft history?'))return false;
 if(acct.id!=null&&confirm('Also delete the copy saved to your account?')){
  try{await api('drafts/'+acct.id+'/','DELETE');acct.id=null;}catch(err){notify(err.message);}
 }
 activeDraft=false;return true;
}
async function caseEditor(t,draft=null){page(`<div class="intro"><div><div class="eyebrow">TEMPORARY CASE DRAFT · FROM MASTER REVISION ${t.version}</div><h1>${esc(t.title)}</h1>${draft?`<p class="${draft.stale_base?'warning':'muted'}">Resumed from the copy you saved to your account on ${new Date(draft.updated_at).toLocaleString()}.${draft.stale_base?` The master template has since advanced to revision ${t.version} (this draft started from ${draft.base_version}).`:''} Nothing you do here changes the master template.</p>`:'<p>A working copy of the saved narrative — pick any built-in options and build the case checklist on the right to fill it in. Nothing you do here changes the master template.</p>'}</div><button id="finish">Finish and clear</button></div><div class="editor-grid"><section class="panel"><label>Case narrative — header excluded</label><div id="case-content"></div><label><input id="case-approved" type="checkbox"> I reviewed this narrative and approve it for copying.</label><div class="actions">${copyButtons()}<button id="case-grammar">Grammar &amp; punctuation check</button><button id="checkpoint">Save checkpoint</button></div>${previewBody()}<div class="actions"><input id="case-save-label" maxlength="200" placeholder="optional note, e.g. left off at node dissection"><button id="case-save-account">Save to my account</button></div><p class="muted">Saving keeps one resumable copy of this narrative per template on your account (7-day expiry), so you can continue on another computer. Only the narrative is saved — no AI output, instructions, or draft history.</p><p class="muted">Copying runs a final grammar &amp; punctuation check (when AI is configured). Copying keeps this draft open. Undo is in the editor. Case edits never change your master template.</p><details id="draft-history"><summary>Draft history</summary><p class="muted">Every proposal and applied change is kept here for this session only — nothing is written to the app database or your browser. Cleared on Finish and clear.</p><div id="draft-history-body"></div></details></section><aside class="panel"><h2>1 · Pick built-in options</h2><p class="muted">Tick any built-in choices for this case — from <code>[[ … ]]</code> fields in the template. These fill in immediately; no AI call, no free typing.</p><div id="case-fields"></div><button id="case-generate">Fill selected options</button><hr class="divider"><h2>2 · Build the case checklist</h2><p class="muted">The main way to finish everything else in an op note. The app lists every remaining placeholder (*** , @AGE@ , {…}) and asks what you did for this case, plus targeted questions about defaults that may not apply. Answer what fits — a “no / none” answer removes the line. Your master template is never changed.</p><button id="checklist" class="primary">Build case checklist</button><div id="checklist-body"></div><hr class="divider"><h2>3 · Clean up leftovers</h2><p class="muted">After the checklist, drop any placeholders you left blank — pasted into Epic as plain text they do not auto-fill.</p><button id="strip-tokens">Strip unresolved placeholders <span id="ph-count"></span></button><hr class="divider"><details id="freetext"><summary>Free-text edit — backup, for anything the checklist did not cover</summary><p class="muted">Describe concepts or facts to work into the narrative; the AI revises the relevant passages and shows a diff to approve.</p><label for="instructions">Instructions</label><textarea id="instructions" placeholder="Significant periprostatic inflammation and scarring made dissection difficult. Revise the relevant narrative…"></textarea><button id="propose">Propose revision</button></details><hr class="divider"><details id="mod22"><summary>Modifier 22 statement — only if this case was substantially more complex</summary><p class="warning">Add this only when you have decided the service was significantly greater than usual and the documentation supports it. This tool does not determine coding eligibility. No time or figure is invented — supply any number yourself.</p><label for="mod22-template">Pull bracketed reasoning from one of your MOD22 templates (optional)</label><select id="mod22-template"><option value="">— none —</option></select><small class="hint">Only templates with “MOD22” in the title or Epic name appear here (e.g. ASMOD22RALP). Its mandated wording and its <code>[bracketed]</code> reason options are sent to the model.</small><div id="mod22-reasons"></div><label for="mod22-factors">Case-specific complexity factors</label><textarea id="mod22-factors" placeholder="e.g. dense adhesions from prior open surgery, morbid obesity, prior pelvic radiation, unexpected bleeding requiring extra dissection"></textarea><label for="mod22-time" id="mod22-time-label">Additional operative time</label><input id="mod22-time" placeholder="e.g. 60 minutes — leave blank to keep the *** placeholder"><small class="hint">The model never estimates time. Enter the number and it fills any “*** minutes” slot; leave it blank and the *** stays for you to complete.</small><button id="mod22-go">Draft modifier-22 statement</button><p class="hint">The statement is appended to the end of the note and shown as a diff to approve.</p></details><p class="warning">Temporary does not mean de-identified. Case text is sent to the configured AI provider only when you request a checklist, a proposal, or a modifier-22 draft. Provider retention may apply.</p></aside></div><div id="reviews"></div>`);activeDraft=true;dirty=false;let graded=false;const acct={id:draft?draft.id:null};function updatePh(){const n=tokenCount(e.getHTML())+((text(e.getHTML()).match(MARK_RX)||[]).length),el=$('#ph-count'),btn=$('#strip-tokens');if(el)el.textContent=n?'('+n+')':'';if(btn)btn.disabled=!n;}const e=rich('#case-content',draft?draft.content:t.content,()=>{$('#case-approved').checked=false;graded=false;updatePh();});const mine=epoch;updatePh();wirePreviewEditor(e);
 accountControls(t,()=>e.getHTML(),'#case-save-label','#case-save-account',acct);if(draft)$('#case-save-label').value=draft.label||'';
 const st=await api('status/').catch(()=>({}));if(epoch!==mine)return;const aiReady=!!st.configured;
 const sharedMap=new Map((st.shared_choices||[]).map(c=>[c.label.toLowerCase(),c.options]));
 const fieldSource=e.getHTML();let lastGenerated=fieldSource;const marks=markerVariables(fieldSource,sharedMap);
 $('#case-fields').innerHTML=marks.length?marks.map((f,vi)=>{
   const free=f.opts.find(o=>/\*{3,}/.test(o)),fixed=f.opts.filter(o=>!/\*{3,}/.test(o));
   const note=f.missing?'<small class="hint warning">Shared variable “'+esc(f.label)+'” is not defined — create it in Settings, or free-type below.</small>':f.source==='shared'?'<small class="hint">Shared list — options are managed in Settings.</small>':f.mixed?'<small class="hint warning">Declared locally and also referenced as [[@…]]; the local list is used.</small>':!f.declared?'<small class="hint warning">No options declared for this variable anywhere in the template — free text only.</small>':f.conflict?'<small class="hint warning">Declared more than once with different options; the first list is used.</small>':'';
   return `<div class="pfield"><p class="check-q">${esc(f.label)}${f.idxs.length>1?` <span class="badge">${f.idxs.length}×</span>`:''}</p>${fixed.map(o=>`<label class="reason"><input type="checkbox" data-cm="${vi}" value="${esc(o)}"> ${esc(o)}</label>`).join('')}<input data-cmfree="${vi}" placeholder="${esc(free?(free.replace(/\*{3,}/,'').trim()||'value'):(fixed.length?'other / free text (optional)':'free text'))}">${note}</div>`;
  }).join(''):'<p class="muted">This template has no <code>[[ … ]]</code> fields. Add one to the master template where a fixed set of options belongs, e.g. <code>[[Extent: RALP without pelvic lymphadenectomy | RALP with standard pelvic lymphadenectomy | RALP with extended pelvic lymphadenectomy]]</code>, then repeat the value elsewhere with just <code>[[Extent]]</code>.</p>';
 action('#case-generate',async()=>{
  const vals=new Map();let filled=0;
  marks.forEach((f,vi)=>{const picks=[...$('#case-fields').querySelectorAll(`input[data-cm="${vi}"]:checked`)].map(c=>c.value);const fx=$(`#case-fields [data-cmfree="${vi}"]`)?.value.trim();const all=[...picks,...(fx?[fx]:[])];if(all.length){const v=joinList(all);f.idxs.forEach(i=>vals.set(i,v));filled++;}});
  if(!marks.length)throw Error('This template has no [[ … ]] fields to fill.');
  if(e.getHTML()!==lastGenerated&&!confirm('Fill from the starting template and current field selections? This replaces manual edits and AI changes in the working narrative. Choose Cancel to keep them. A checkpoint will preserve the current note.'))return;
  pushHistory('Before filling options');
  e.commands.setContent(safe(fillMarkers(fieldSource,vals)));lastGenerated=e.getHTML();$('#case-approved').checked=false;updatePh();
  pushHistory('Filled '+filled+' option'+(filled===1?'':'s'));
  notify(filled+' option'+(filled===1?'':'s')+' filled. Review before copying.');
 });
 const history=[];
 function pushHistory(label,html){const h=html??e.getHTML();if(history[0]&&history[0].html===h)return;history.unshift({t:new Date(),label,html:h});if(history.length>50)history.pop();renderHistory();}
 function renderHistory(){const body=$('#draft-history-body');body.innerHTML=history.map((h,i)=>`<div class="hist"><div class="hist-head"><strong>${esc(h.label)}</strong><small>${h.t.toLocaleTimeString([],{hour:'numeric',minute:'2-digit',second:'2-digit'})}</small></div><div class="actions"><button data-hview="${i}">View</button><button data-hcopy="${i}">Copy</button><button data-hrestore="${i}">Restore</button></div><div class="hist-doc document" hidden></div></div>`).join('')||'<p class="muted">No snapshots yet.</p>';
  body.querySelectorAll('[data-hview]').forEach(b=>b.onclick=()=>{const d=b.closest('.hist').querySelector('.hist-doc');d.hidden=!d.hidden;if(!d.hidden)d.innerHTML=safe(history[+b.dataset.hview].html);});
  body.querySelectorAll('[data-hcopy]').forEach(b=>b.onclick=()=>copy(history[+b.dataset.hcopy].html,true).catch(err=>notify(err.message)));
  body.querySelectorAll('[data-hrestore]').forEach(b=>b.onclick=()=>{const h=history[+b.dataset.hrestore];if(confirm('Restore the case narrative to "'+h.label+'" ('+h.t.toLocaleTimeString()+')? Current unsaved edits are replaced.')){e.commands.setContent(safe(h.html));$('#case-approved').checked=false;pushHistory('Restored: '+h.label);notify('Restored. Review before copying.');}});}
 pushHistory('Starting narrative');renderHistory();
 async function runGrammar(){const source=e.getHTML();const r=await api('grammar/','POST',{content:source});if(epoch!==mine)return true;assertSource(e,source);graded=true;
  if(r.provider==='mock'){notify('MOCK provider — no grammar check performed.');return false;}
  if(r.proposal.content===e.getHTML()){notify('Grammar & punctuation check: nothing to fix.');return false;}
  showProvider(r.provider);pushHistory('Grammar proposal',r.proposal.content);$('#reviews').innerHTML='';
  reviewCard($('#reviews'),r.proposal,async html=>{assertSource(e,source);e.commands.setContent(html);$('#case-approved').checked=false;graded=true;pushHistory('Applied grammar fixes');notify('Grammar fixes applied to the draft. Re-check “approve for copying”, then Copy.');});
  notify('Grammar & punctuation suggestions ready — review below, then approve and copy.');return true;}
 action('#case-grammar',()=>runGrammar());
 async function caseCopy(formatted){if(!$('#case-approved').checked)throw Error('Review and approve the current narrative before copying.');
  const left=tokenCount(e.getHTML())+((text(e.getHTML()).match(MARK_RX)||[]).length);if(left&&!confirm(left+' unresolved placeholder'+(left>1?'s':'')+' (like @AGE@, ***, or [[ … ]]) remain and will paste as literal text into Epic. Copy anyway?'))throw Error('Copy cancelled — resolve them above or Strip unresolved placeholders.');
  if(aiReady&&!graded){const source=e.getHTML();try{if(await runGrammar())return;}catch(err){if(epoch!==mine)return;if(e.getHTML()===source)graded=true;notify(err.message+' Click Copy again to copy without the check.');return;}}
  if(epoch!==mine)return;
  await copy(e.getHTML(),formatted);}
 action('#copy-plain',()=>caseCopy(false));action('#copy-rich',()=>caseCopy(true));
 action('#checkpoint',()=>{pushHistory('Checkpoint');$('#draft-history').open=true;notify('Checkpoint saved to draft history (this session only).');});
 action('#strip-tokens',()=>{const left=tokenCount(e.getHTML())+((text(e.getHTML()).match(MARK_RX)||[]).length);if(!left){notify('No unresolved placeholders in the narrative.');return;}if(!confirm('Remove all '+left+' remaining placeholder'+(left>1?'s':'')+' ([[ … ]], @…@, {…}, ***) from the case draft? Review the result — some sentences may need a manual touch-up.'))return;pushHistory('Before strip');e.commands.setContent(safe(stripTokens(e.getHTML(),true)));$('#case-approved').checked=false;pushHistory('Stripped placeholders');updatePh();notify(left+' placeholder'+(left>1?'s':'')+' removed. Review the narrative before copying.');},()=>tokenCount(e.getHTML())+((text(e.getHTML()).match(MARK_RX)||[]).length)>0);
 action('#finish',async()=>{if(await finishAndClear(acct))return library();});
 action('#propose',async()=>{const source=e.getHTML();const result=await api('propose/','POST',{mode:'case',ids:[t.id],content:source,instruction:$('#instructions').value});if(epoch!==mine)return;pushHistory('Proposed revision',result.proposals[0].content);$('#reviews').innerHTML='';showProvider(result.provider);reviewCard($('#reviews'),result.proposals[0],async html=>{if(e.getHTML()!==source)throw Error('The working narrative changed after this proposal. Reject and request a new proposal to preserve manual edits.');guardHeadings(source,html);e.commands.setContent(html);$('#case-approved').checked=false;pushHistory('Applied AI revision');notify('Applied to temporary draft only. Review before copying.');});});
 let mod22Tpls=[];
 api('templates/').then(r=>{const sel=$('#mod22-template');if(!sel)return;mod22Tpls=(r.items||[]).filter(x=>/mod\s?22/i.test((x.epic_name||'')+' '+(x.title||'')));mod22Tpls.forEach(x=>{const o=document.createElement('option');o.value=x.id;o.textContent=(x.epic_name||x.title)+(x.epic_name&&x.title!==x.epic_name?' — '+x.title:'');sel.append(o);});if(!mod22Tpls.length)sel.nextElementSibling?.insertAdjacentHTML('beforeend',' <strong>None found — add “MOD22” to a template name.</strong>');
  sel.onchange=()=>{const tpl=mod22Tpls.find(x=>x.id==sel.value),box=$('#mod22-reasons');if(!box)return;const plain=tpl?text(tpl.content):'';const opts=tpl?[...new Set((plain.match(/\[[^\[\]\n]{2,400}\]/g)||[]).flatMap(s=>s.slice(1,-1).split(/\s*\/\s*/)).map(x=>x.trim()).filter(x=>x.length>2))]:[];box.innerHTML=opts.length?'<p class="hint">Tick the reasons from this template that apply to this case — each ticked reason must appear in the statement.</p>'+opts.map(o=>`<label class="reason"><input type="checkbox" value="${esc(o)}"> ${esc(o)}</label>`).join(''):(tpl?'<p class="hint">This template has no [bracketed] reason options — its wording is still used.</p>':'');const needsTime=/\*{3,}[^.\n]{0,20}(minute|hour|hr\b)|(additional|extra|increased)[^.\n]{0,30}(operative|surgical)[^.\n]{0,10}time/i.test(plain);const tl=$('#mod22-time-label');if(tl)tl.textContent='Additional operative time'+(needsTime?' — your template records this':'');};
 }).catch(()=>{});
 action('#mod22-go',async()=>{const source=e.getHTML();const tid=+$('#mod22-template').value||null;const time=$('#mod22-time').value.trim();const factors=[time?('Additional operative time: '+time):'',$('#mod22-factors').value.trim()].filter(Boolean).join('. ');const reasons=[...$('#mod22-reasons').querySelectorAll('input:checked')].map(c=>c.value);if(!factors&&!reasons.length)throw Error('Enter the complexity factors or the additional time, or tick at least one reason from your template.');const r=await api('mod22/','POST',{content:source,factors,template_id:tid,reasons});if(epoch!==mine)return;pushHistory('Modifier-22 proposal',r.proposal.content);$('#reviews').innerHTML='';showProvider(r.provider);reviewCard($('#reviews'),r.proposal,async html=>{if(e.getHTML()!==source)throw Error('The working narrative changed after this proposal. Reject and rerun to keep your edits.');e.commands.setContent(html);$('#case-approved').checked=false;pushHistory('Added modifier-22 statement');notify('Modifier-22 statement added. Review the wording against your payer requirements before copying.');});});
 let checklistSource=null;
 function renderChecklist(items){const body=$('#checklist-body');if(!items.length){body.innerHTML='<p class="muted">No unresolved placeholders found and no checklist questions returned.</p>';return;}
  let i=0;const nph=items.filter(x=>x.placeholder).length;
  body.innerHTML=(nph?`<p class="muted">${nph} unresolved placeholder${nph>1?'s':''} (like @AGE@, ***). Resolve each below — they paste into Epic as literal text.</p>`:'')+items.map(it=>{
   if(!it.placeholder)return `<div class="check"><p class="check-q">${esc(it.question)}</p><textarea data-q data-qtext="${esc(it.question)}" placeholder="Your answer (leave blank to skip)"></textarea></div>`;
   const idx=i++,tok=it.token||'***';
   return `<div class="check"><p class="check-ctx">${esc(it.context||'').replace(TOKEN_RX,m=>'<mark>'+esc(m)+'</mark>')}</p><p class="check-q">${esc(it.question)}</p><textarea data-fill="${idx}" placeholder="Your answer"></textarea><div class="check-opts"><label><input type="checkbox" data-literal="${idx}"> insert exactly as typed</label><select data-mode="${idx}"><option value="fill">Use my answer</option><option value="keep">Keep ${esc(tok)} as an Epic field</option><option value="remove">Remove this line</option></select></div></div>`;
  }).join('')+`<p class="hint">Answer with what you did. If a step did not happen, answer “no” / “none” (the line is deleted, not negated) or pick “Remove this line”.</p><button id="apply-checklist" class="primary">Apply answers</button>`;
  action('#apply-checklist',applyChecklist);}
 const NEG=/^\s*(no|none|n\/?a|nil|negative|not\s+(applicable|done|placed|performed|used|indicated|present)|(we\s+)?did\s?n.?.?t|didn.?t|was\s+not|were\s+not|omit(ted)?|remove[d]?|skip(ped)?)\b/i;
 async function applyChecklist(){if(checklistSource===null||e.getHTML()!==checklistSource)throw Error('The narrative changed. Rebuild the checklist before applying answers.');const body=$('#checklist-body');const subs=new Map(),removeIdx=new Set(),removed=[],qa=[];
  body.querySelectorAll('[data-fill]').forEach(ta=>{const idx=+ta.dataset.fill,card=ta.closest('.check'),mode=card.querySelector(`select[data-mode="${idx}"]`).value,lit=card.querySelector(`[data-literal="${idx}"]`).checked,txt=ta.value.trim();
   const ctx=card.querySelector('.check-ctx')?.textContent?.trim()||('fill-in #'+idx),q=card.querySelector('.check-q')?.textContent?.trim()||ctx;
   if(mode==='remove'){removeIdx.add(idx);removed.push(ctx);}
   else if(mode==='fill'&&txt){if(NEG.test(txt)){removeIdx.add(idx);removed.push(ctx+'  — you answered “'+txt+'”');}else if(lit)subs.set(idx,txt);else qa.push({question:q,answer:txt});}});
  body.querySelectorAll('[data-q]').forEach(ta=>{if(ta.value.trim())qa.push({question:ta.dataset.qtext,answer:ta.value.trim()});});
  if(removeIdx.size&&!confirm('Remove these lines entirely from the case draft?\n\n• '+removed.join('\n• ')))return;
  if(!subs.size&&!removeIdx.size&&!qa.length){notify('Answer at least one item first.');return;}
  checklistSource=null;body.innerHTML='<p class="muted">Answers submitted. Rebuild the checklist to continue filling this draft.</p>';
  const applied=applyFills(e.getHTML(),subs,removeIdx);e.commands.setContent(safe(applied));$('#case-approved').checked=false;
  const msg=[];if(subs.size)msg.push(subs.size+' inserted verbatim');if(removeIdx.size)msg.push(removeIdx.size+' line'+(removeIdx.size>1?'s':'')+' removed');if(msg.length){pushHistory('Applied '+msg.join(' + '));notify(msg.join(', ')+'. Review before copying.');}
  if(!qa.length)return;
  const base=e.getHTML();const r=await api('finalize/','POST',{content:base,answers:qa});if(epoch!==mine)return;
  pushHistory('Proposed from checklist',r.proposal.content);
  $('#reviews').innerHTML='';showProvider(r.provider);
  reviewCard($('#reviews'),r.proposal,async html=>{if(e.getHTML()!==base)throw Error('The narrative changed after this proposal. Reject and rebuild the checklist to keep your edits.');guardHeadings(base,html);e.commands.setContent(html);$('#case-approved').checked=false;pushHistory('Applied checklist answers');notify('Checklist answers applied to the temporary draft. Review before copying.');});}
 action('#checklist',async()=>{const source=e.getHTML();let items=[],note='Checklist ready. Answer the questions and fill-ins, then Apply.';try{const r=await api('finalize/','POST',{content:source,step:'questions'});items=r.items||[];if(r.degraded)note='AI checklist unavailable — the *** fill-ins are listed for you to complete manually.';else if(r.provider==='mock')note='MOCK provider — checklist questions are not a clinical review.';}catch(err){note='Checklist unavailable: '+err.message;}if(epoch!==mine)return;if(e.getHTML()!==source){checklistSource=null;throw Error('The narrative changed while building the checklist. Rebuild it for the current draft.');}checklistSource=source;renderChecklist(items);notify(note);});
 notify(marks.length?'Pick any built-in options above, then “Build case checklist” for everything else.':'Start with “Build case checklist” to fill in every placeholder and confirm the defaults for this case.');}
async function procedureEditor(t,draft=null){
 page(`<div class="intro"><div><div class="eyebrow">TEMPORARY PROCEDURE DRAFT · FROM MASTER REVISION ${t.version}</div><h1>${esc(t.title)}</h1>${draft?`<p class="${draft.stale_base?'warning':'muted'}">Resumed from the copy you saved to your account on ${new Date(draft.updated_at).toLocaleString()}.${draft.stale_base?` The master template has since advanced to revision ${t.version} (this draft started from ${draft.base_version}).`:''} Nothing here changes the master template.</p>`:'<p>A working copy — tick the findings on the right, then Generate. Nothing here changes the master template.</p>'}</div><button id="finish">Finish and clear</button></div><div class="editor-grid"><section class="panel"><label>Procedure note — working draft</label><div id="p-content"></div><label><input id="p-approved" type="checkbox"> I reviewed this note and approve it for copying.</label><div class="actions">${copyButtons()}<button id="p-grammar">Grammar &amp; punctuation check</button><button id="p-checkpoint">Save checkpoint</button></div>${previewBody()}<div class="actions"><input id="p-save-label" maxlength="200" placeholder="optional note, e.g. left off before impressions"><button id="p-save-account">Save to my account</button></div><p class="muted">Saving keeps one resumable copy of this note per template on your account (7-day expiry), so you can continue on another computer. Only the note text is saved — no AI output, instructions, or draft history.</p><details id="draft-history"><summary>Draft history</summary><p class="muted">Kept for this session only — nothing is written to the app database or your browser. Cleared on Finish and clear.</p><div id="draft-history-body"></div></details></section><aside class="panel"><h2>1 · Fill in the procedure</h2><p class="muted">Tick the common findings and fill any values, then Generate. The fields come from the <code>[[ … ]]</code> markers in this template; an unfilled marker stays as a placeholder.</p><div id="p-fields"></div><label><input type="checkbox" id="p-smooth"> After filling, ask AI to fix grammar line by line so the findings read as full sentences (reviewed diff; off by default). Deterministic fill alone is safe — this step can only tidy wording, never delete or merge lines.</label><button id="p-generate" class="primary">Generate note</button><hr class="divider"><h2>2 · Clean up leftovers</h2><p class="muted">Drop any <code>[[ … ]]</code> or *** placeholders you left blank — they paste into Epic as literal text.</p><button id="p-strip">Strip unfilled placeholders <span id="p-count"></span></button><hr class="divider"><details id="freetext"><summary>Free-text edit — backup, for anything the fields did not cover</summary><label for="instructions">Instructions</label><textarea id="instructions" placeholder="e.g. add that the patient tolerated the procedure well and will follow up in two weeks"></textarea><button id="propose">Propose revision</button></details><p class="warning">Temporary does not mean de-identified. Text is sent to the configured AI provider only when you Generate with smoothing, run the grammar check, or propose a revision. Provider retention may apply.</p></aside></div><div id="reviews"></div>`);
 activeDraft=true;dirty=false;let graded=false;const acct={id:draft?draft.id:null};
 function updatePc(){const n=((text(e.getHTML()).match(MARK_RX)||[]).length)+tokenCount(e.getHTML());const el=$('#p-count'),b=$('#p-strip');if(el)el.textContent=n?'('+n+')':'';if(b)b.disabled=!n;}
 const e=rich('#p-content',draft?draft.content:t.content,()=>{$('#p-approved').checked=false;graded=false;updatePc();});const mine=epoch;wirePreviewEditor(e);
 accountControls(t,()=>e.getHTML(),'#p-save-label','#p-save-account',acct);if(draft)$('#p-save-label').value=draft.label||'';
 const st=await api('status/').catch(()=>({}));if(epoch!==mine)return;const aiReady=!!st.configured;
 const sharedMap=new Map((st.shared_choices||[]).map(c=>[c.label.toLowerCase(),c.options]));
 const history=[];
 function pushHistory(label,html){const h=html??e.getHTML();if(history[0]&&history[0].html===h)return;history.unshift({t:new Date(),label,html:h});if(history.length>50)history.pop();renderHistory();}
 function renderHistory(){const body=$('#draft-history-body');body.innerHTML=history.map((h,i)=>`<div class="hist"><div class="hist-head"><strong>${esc(h.label)}</strong><small>${h.t.toLocaleTimeString([],{hour:'numeric',minute:'2-digit',second:'2-digit'})}</small></div><div class="actions"><button data-hview="${i}">View</button><button data-hcopy="${i}">Copy</button><button data-hrestore="${i}">Restore</button></div><div class="hist-doc document" hidden></div></div>`).join('')||'<p class="muted">No snapshots yet.</p>';
  body.querySelectorAll('[data-hview]').forEach(b=>b.onclick=()=>{const d=b.closest('.hist').querySelector('.hist-doc');d.hidden=!d.hidden;if(!d.hidden)d.innerHTML=safe(history[+b.dataset.hview].html);});
  body.querySelectorAll('[data-hcopy]').forEach(b=>b.onclick=()=>copy(history[+b.dataset.hcopy].html,true).catch(err=>notify(err.message)));
  body.querySelectorAll('[data-hrestore]').forEach(b=>b.onclick=()=>{const h=history[+b.dataset.hrestore];if(confirm('Restore the note to “'+h.label+'” ('+h.t.toLocaleTimeString()+')? Current unsaved edits are replaced.')){e.commands.setContent(safe(h.html));$('#p-approved').checked=false;pushHistory('Restored: '+h.label);notify('Restored. Review before copying.');}});}
 pushHistory('Starting note');renderHistory();updatePc();
 const fieldSource=e.getHTML();let lastGenerated=fieldSource;const marks=markerVariables(fieldSource,sharedMap);
 $('#p-fields').innerHTML=marks.length?marks.map((f,vi)=>{
   const free=f.opts.find(o=>/\*{3,}/.test(o)),fixed=f.opts.filter(o=>!/\*{3,}/.test(o));
   const note=f.missing?'<small class="hint warning">Shared variable “'+esc(f.label)+'” is not defined — create it in Settings, or free-type below.</small>':f.source==='shared'?'<small class="hint">Shared list — options are managed in Settings.</small>':f.mixed?'<small class="hint warning">Declared locally and also referenced as [[@…]]; the local list is used.</small>':!f.declared?'<small class="hint warning">No options declared for this variable anywhere in the note — free text only.</small>':f.conflict?'<small class="hint warning">Declared more than once with different options; the first list is used.</small>':'';
   return `<div class="pfield"><p class="check-q">${esc(f.label)}${f.idxs.length>1?` <span class="badge">${f.idxs.length}×</span>`:''}</p>${fixed.map(o=>`<label class="reason"><input type="checkbox" data-m="${vi}" value="${esc(o)}"> ${esc(o)}</label>`).join('')}<input data-mfree="${vi}" placeholder="${esc(free?(free.replace(/\*{3,}/,'').trim()||'value'):(fixed.length?'other / free text (optional)':'free text'))}">${note}</div>`;
  }).join(''):'<p class="muted">This template has no <code>[[ … ]]</code> fields. Edit the note directly on the left, or add markers to the master — e.g. <code>[[Bladder: normal | trabeculation | diverticulum | mass]]</code>, then repeat a value elsewhere with just <code>[[Bladder]]</code>.</p>';
 async function runGrammar(){const source=e.getHTML();const r=await api('grammar/','POST',{content:source});if(epoch!==mine)return true;assertSource(e,source);graded=true;
  if(r.provider==='mock'){notify('MOCK provider — no grammar check performed.');return false;}
  if(r.proposal.content===e.getHTML()){notify('Grammar & punctuation check: nothing to fix.');return false;}
  showProvider(r.provider);pushHistory('Grammar proposal',r.proposal.content);$('#reviews').innerHTML='';
  reviewCard($('#reviews'),r.proposal,async html=>{assertSource(e,source);e.commands.setContent(html);$('#p-approved').checked=false;graded=true;pushHistory('Applied grammar fixes');notify('Grammar fixes applied. Re-check “approve for copying”, then Copy.');});
  notify('Grammar & punctuation suggestions ready — review below.');return true;}
 action('#p-grammar',()=>runGrammar());
 async function pCopy(formatted){if(!$('#p-approved').checked)throw Error('Review and approve the note before copying.');
  const left=((text(e.getHTML()).match(MARK_RX)||[]).length)+tokenCount(e.getHTML());
  if(left&&!confirm(left+' unfilled placeholder'+(left>1?'s':'')+' ([[ … ]] or ***) remain and paste into Epic as literal text. Copy anyway?'))throw Error('Copy cancelled — fill or strip the placeholders first.');
  if(aiReady&&!graded){const source=e.getHTML();try{if(await runGrammar())return;}catch(err){if(epoch!==mine)return;if(e.getHTML()===source)graded=true;notify(err.message+' Click Copy again to copy without the check.');return;}}
  if(epoch!==mine)return;
  await copy(e.getHTML(),formatted);}
 action('#copy-plain',()=>pCopy(false));action('#copy-rich',()=>pCopy(true));
 action('#p-checkpoint',()=>{pushHistory('Checkpoint');$('#draft-history').open=true;notify('Checkpoint saved to draft history (this session only).');});
 action('#p-strip',()=>{const m=(text(e.getHTML()).match(MARK_RX)||[]).length,toks=tokenCount(e.getHTML());if(!m&&!toks){notify('No unfilled placeholders in the note.');return;}if(!confirm('Remove all '+(m+toks)+' remaining placeholder'+(m+toks>1?'s':'')+' ([[ … ]], @…@, {…}, ***)? Review the result — some sentences may need a touch-up.'))return;pushHistory('Before strip');const h=stripTokens(e.getHTML(),true);e.commands.setContent(safe(h));$('#p-approved').checked=false;pushHistory('Stripped placeholders');updatePc();notify('Placeholders removed. Review the note before copying.');},()=>((text(e.getHTML()).match(MARK_RX)||[]).length)+tokenCount(e.getHTML())>0);
 action('#finish',async()=>{if(await finishAndClear(acct))return library();});
 action('#propose',async()=>{const source=e.getHTML();const result=await api('propose/','POST',{mode:'case',ids:[t.id],content:source,instruction:$('#instructions').value});if(epoch!==mine)return;pushHistory('Proposed revision',result.proposals[0].content);$('#reviews').innerHTML='';showProvider(result.provider);reviewCard($('#reviews'),result.proposals[0],async html=>{if(e.getHTML()!==source)throw Error('The working note changed after this proposal. Reject and request a new one to keep manual edits.');guardHeadings(source,html);e.commands.setContent(html);$('#p-approved').checked=false;pushHistory('Applied AI revision');notify('Applied to temporary draft only. Review before copying.');});});
 action('#p-generate',async()=>{
  const vals=new Map();let filled=0;
  marks.forEach((f,vi)=>{const picks=[...$('#p-fields').querySelectorAll(`input[data-m="${vi}"]:checked`)].map(c=>c.value);const fx=$(`#p-fields [data-mfree="${vi}"]`)?.value.trim();const all=[...picks,...(fx?[fx]:[])];if(all.length){const v=joinList(all);f.idxs.forEach(i=>vals.set(i,v));filled++;}});
  if(!marks.length)throw Error('This template has no procedure fields. Edit the note directly.');
  if(e.getHTML()!==lastGenerated&&!confirm('Regenerate from the starting template and current field selections? This replaces manual edits and AI changes in the working note. Choose Cancel to keep them. A checkpoint will preserve the current note.'))return;
  pushHistory('Before filling fields');
  e.commands.setContent(safe(fillMarkers(fieldSource,vals)));lastGenerated=e.getHTML();$('#p-approved').checked=false;updatePc();
  pushHistory('Filled '+filled+' field'+(filled===1?'':'s'));
  notify(filled+' field'+(filled===1?'':'s')+' filled. '+($('#p-smooth').checked&&aiReady?'Review the AI polish below.':'Review before copying.'));
  if(!($('#p-smooth').checked&&aiReady))return;
  const base=e.getHTML();
  const r=await api('propose/','POST',{mode:'case',ids:[t.id],content:base,instruction:"Rewrite ONLY for grammar so each line reads as a complete sentence in the author's clinical voice: for example 'Meatus: normal caliber.' becomes 'The meatus was of normal caliber.' and 'Estimated blood loss minimal.' becomes 'Estimated blood loss was minimal.'. When a line starts with a 'Label:' prefix and you open the sentence with that same subject, drop the redundant prefix. Do NOT delete, merge, condense, summarise, or reorder any sentence, heading or line. Reproduce every heading and every other sentence exactly. Add nothing that is not already written — no findings, measurements, steps, devices or medications. Leave every remaining [[ ... ]] and *** EXACTLY as written, including the text inside the brackets. Return the complete note, every line."});
  if(epoch!==mine)return;const prop=r.proposals[0];prop.content=restoreMarkers(base,prop.content);pushHistory('Smoothed proposal',prop.content);$('#reviews').innerHTML='';showProvider(r.provider);
  reviewCard($('#reviews'),prop,async html=>{if(e.getHTML()!==base)throw Error('The note changed after this proposal. Reject and regenerate.');guardShrink(base,html);e.commands.setContent(html);$('#p-approved').checked=false;updatePc();pushHistory('Applied smoothed note');notify('Applied to temporary draft only. Review before copying.');});
 });
 notify(marks.length?'Tick the findings on the right, then Generate note.':'This template has no [[ … ]] fields yet — edit on the left, or add markers to the master template.');
}
function showProvider(provider){notify(provider==='mock'?'MOCK provider — synthetic demonstration, not a clinical AI editor.':'Proposal ready for your review.');}
async function batch(){const ids=[...selected];if(ids.length>10)throw Error('Select no more than 10 templates per update.');const items=await Promise.all(ids.map(id=>api(`templates/${id}/`)));page(`<div class="intro"><div><div class="eyebrow">SELECTED MASTER UPDATE</div><h1>Review a practice change</h1><p>Only these ${ids.length} explicitly selected masters can be approved in this review.</p></div><button id="back">Back to library</button></div><section class="panel"><div>${items.map(t=>`<span class="badge">${esc(t.title)} · r${t.version}</span>`).join('')}</div><label for="instruction">Describe your practice change</label><textarea id="instruction"></textarea><button id="propose" class="primary">Propose selected updates</button><div id="reviews"></div></section>`);const mine=epoch;action('#back',()=>{if(leave())return library();});action('#propose',async()=>{const result=await api('propose/','POST',{mode:'master',ids,instruction:$('#instruction').value});if(mine!==epoch)return;dirty=true;$('#reviews').innerHTML='';showProvider(result.provider);result.proposals.forEach(p=>{const section=document.createElement('div');const h=document.createElement('h2');h.textContent=items.find(t=>t.id===p.id).title;section.append(h);$('#reviews').append(section);reviewCard(section,p,async content=>{guardHeadings(p.source,content);const saved=await api('approve/','POST',{scope:result.scope,id:p.id,content,review_tokens:true});notify('Master saved as revision '+saved.version+'. Other masters unchanged.');});});});}
async function settings(){const s=await api('status/');page(`<div class="intro"><div><div class="eyebrow">PRIVATE WORKSPACE</div><h1>Settings & portability</h1></div></div><div class="editor-grid"><section class="panel"><h2>Account</h2><p>Signed in as <strong>${esc(s.username)}</strong>. Public signup is disabled.</p><a href="/password/">Change password</a><hr class="divider"><h2>AI configuration</h2><p>Provider: <strong>${esc(s.provider)}</strong><br>Model: ${esc(s.model||'Not configured')}<br>Endpoint: ${esc(s.endpoint||'—')}<br>Status: ${s.configured?'Configured — the Customize this case and Update selected masters flows will call it':'Not configured — manual editing only'}</p><p class="warning">${s.provider==='mock'?'MOCK: deterministic demonstration only. No external AI requests.':'Review your provider agreement and retention settings before sending sensitive content.'}</p><p>Provider, model, endpoint, and credentials are configured in server environment variables. Secrets are never shown here. Manual search, edit, and copy work without AI.</p></section><section class="panel"><h2>Backup & import</h2><p>Export contains reusable templates, original sources, metadata, revision history, and your shared choice variables. Treat it as private data. Case drafts are never included.</p><a href="/api/export/">Download library backup (JSON)</a><label for="backup">Review a portable backup</label><input type="file" id="backup" accept=".json,application/json"><div id="import-review"></div><hr class="divider"><h2>Privacy boundary</h2><p>Case drafts and instructions live in browser memory and transient server/provider request processing. No draft database, browser storage, analytics, or case request logging is implemented. Browser, operating system, clipboard, hosting, and provider retention remain separate considerations.</p><p>Login alone does not approve this application for identifiable clinical data. See README for deployment requirements and Epic paste checks.</p></section><section class="panel"><h2>Shared choice variables</h2><p class="muted">Named option lists — your assistant roster, attendings, and so on. Reference one in any template as <code>[[@Name]]</code>; edit the list here once and every template that uses it follows. Filling stays deterministic and is never sent to the AI.</p><div id="choice-list"></div><hr class="divider"><label for="new-choice-label">New variable name</label><input id="new-choice-label" placeholder="Assistant"><label for="new-choice-options">Options — one per line or | -separated</label><textarea id="new-choice-options" placeholder="James&#10;David&#10;Teresa"></textarea><button id="add-choice">Add variable</button></section><section class="panel"><h2>Copy &amp; paste formatting</h2><p class="warning">Confirmed in real hospital use: an Epic Op Note field discards <em>all</em> inbound clipboard formatting on paste, even from <strong>Copy formatted</strong>. Treat plain text as the only reliable channel unless you've verified otherwise for a specific field.</p><p><strong>Bold has no plain-text equivalent</strong> and is not simulated with a marker character (that would collide with the <code>***</code> unresolved-placeholder convention) — this is an Epic limitation, not something the app can work around.</p><p><strong>Wrapped lines merge automatically.</strong> Copying re-flows Epic's hard-wrapped lines back into flowing paragraphs — the same merge as the master editor's <strong>Reflow wrapped lines</strong> button — even if a template was pasted in and never manually reflowed.</p><p><strong>Which lines stay tight vs. get a blank line:</strong></p><ul><li>A short <code>Label:</code> line (1–2 words — <code>Procedure:</code>, <code>Anesthesia:</code>, <code>Antibiotics:</code>, <code>Blood Loss:</code>, <code>Drains/Tubes:</code>, <code>Grafts/Implants:</code>, <code>Specimens:</code>) stays clumped tight against its neighbors, like Epic's own header block.</li><li>A <em>bare</em> short label — nothing after the colon on its own line, like <code>Procedure:</code> — also stays tight against the plain line(s) that follow as its value (e.g. one or more listed CPT lines), chaining through further unlabeled lines until the next label or heading closes it.</li><li>A longer label (3+ words — <code>Indication for Procedure:</code>, <code>Description of Procedure:</code>) is treated as a section heading and always gets blank-line spacing on both sides.</li><li>Everything else — flowing narrative paragraphs — gets a blank line between distinct paragraphs.</li></ul><p><strong>Manual cleanup still matters.</strong> A stray blank paragraph left over from a paste or import reads as an intentional section break and is never merged away automatically — there's no way to tell "intentional break" from "leftover blank line" programmatically, so remove those by hand during review.</p><p>Use <strong>Preview Epic paste</strong> (next to the copy buttons, and next to Reflow wrapped lines in the master editor) to see exactly what will be copied before you paste it into Epic.</p></section></div>`);
 async function loadChoices(){const box=$('#choice-list');if(!box)return;const r=await api('choices/');
  box.innerHTML=r.items.map(c=>`<div class="pfield" data-choice="${c.id}"><p class="check-q">${esc(c.label)}</p><textarea data-copts>${esc(c.options.join('\n'))}</textarea><div class="actions"><button data-save-choice>Save options</button><button data-del-choice class="danger">Delete</button></div></div>`).join('')||'<p class="muted">No shared variables yet. Add one below.</p>';
  box.querySelectorAll('[data-save-choice]').forEach(b=>b.onclick=async()=>{const row=b.closest('[data-choice]');try{await api('choices/','POST',{label:row.querySelector('.check-q').textContent,options:row.querySelector('[data-copts]').value});notify('Saved.');await loadChoices();}catch(err){notify(err.message);}});
  box.querySelectorAll('[data-del-choice]').forEach(b=>b.onclick=async()=>{const row=b.closest('[data-choice]');if(!confirm('Delete this shared variable? Any [[@…]] reference to it falls back to a free-text field.'))return;try{await api('choices/'+row.dataset.choice+'/','DELETE');notify('Deleted.');await loadChoices();}catch(err){notify(err.message);}});}
 action('#add-choice',async()=>{await api('choices/','POST',{label:$('#new-choice-label').value,options:$('#new-choice-options').value});$('#new-choice-label').value='';$('#new-choice-options').value='';notify('Added.');await loadChoices();});
 loadChoices().catch(e=>notify(e.message));
 $('#backup').onchange=async e=>{try{const file=e.target.files[0];if(!file)return;if(file.size>1_900_000)throw Error('Backup exceeds the 1.9 MB import limit. Use database restore for larger backups.');const data=JSON.parse(await file.text());if(data.format!=='smartphrase-v1'||!Array.isArray(data.items))throw Error('Not a supported backup.');$('#import-review').innerHTML=`<p>${data.items.length} templates will be imported as new independent copies:</p><ul>${data.items.map(t=>`<li>${esc(t.title)} · ${esc(t.version)} revisions</li>`).join('')}</ul><button id="import" class="primary">Approve backup import</button>`;action('#import',async()=>{const r=await api('import/','POST',data);$('#import-review').innerHTML='';notify('Imported '+r.imported+' templates'+(r.shared_choices?' and '+r.shared_choices+' shared choice variables':'')+'.');await loadChoices().catch(()=>{});});}catch(err){notify(err.message);}};}
$('#library-nav').onclick=()=>{if(leave())library().catch(e=>notify(e.message));};$('#imports-nav').onclick=()=>{if(leave()){activeDraft=false;dirty=false;imports().catch(e=>notify(e.message));}};$('#settings-nav').onclick=()=>{if(leave()){activeDraft=false;dirty=false;settings().catch(e=>notify(e.message));}};
window.addEventListener('beforeunload',e=>{if(activeDraft||dirty){e.preventDefault();e.returnValue='';}});
window.addEventListener('pagehide',()=>{editors.forEach(e=>e.destroy());app.replaceChildren();});
window.addEventListener('pageshow',e=>{if(e.persisted)location.reload();});
library().catch(e=>notify(e.message));
