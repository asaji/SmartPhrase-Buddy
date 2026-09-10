import json
from functools import wraps
from django.conf import settings
from django.core import signing
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.debug import sensitive_post_parameters
from django.db.models import Q
from django.utils import timezone
from .models import Template, Revision, PendingImport, CaseDraft
from .services import normalize,serialize,snapshot,plain,propose,tokens,warnings

@login_required
@ensure_csrf_cookie
def index(request): return render(request,'index.html')

def api(methods):
    def deco(fn):
        @wraps(fn)
        @sensitive_post_parameters()
        def wrapped(request,*args,**kwargs):
            if not request.user.is_authenticated: return JsonResponse({'error':'Login required.'},status=401)
            if request.method not in methods: return JsonResponse({'error':'Method not allowed.'},status=405)
            try:
                data=json.loads(request.body) if request.body else {}
                if not isinstance(data,dict): raise ValueError('Expected JSON object.')
                return fn(request,data,*args,**kwargs)
            except (Template.DoesNotExist,PendingImport.DoesNotExist,CaseDraft.DoesNotExist): return JsonResponse({'error':'Not found.'},status=404)
            except (ValueError,TypeError,KeyError,signing.BadSignature) as e: return JsonResponse({'error':str(e) if isinstance(e,ValueError) else 'Invalid request or expired review.'},status=400)
        return wrapped
    return deco

def own(request,pk): return Template.objects.get(pk=pk,owner=request.user)
def record(t): Revision.objects.create(template=t,version=t.version,snapshot=snapshot(t))
def replace(t,data,expected):
    values=normalize(data)
    if t.version!=expected: raise ValueError('Template changed in another window. Reload before saving.')
    # Conditional update prevents lost updates even when requests race.
    from django.utils import timezone
    if Template.objects.filter(pk=t.pk,version=expected).update(**values,version=expected+1,updated_at=timezone.now())!=1: raise ValueError('Concurrent update. Reload before saving.')
    t.refresh_from_db(); record(t)

@api(['GET','POST'])
def templates(request,data):
    if request.method=='POST':
        with transaction.atomic():
            pending_id=data.get('pending_import_id')
            if pending_id is not None:
                if type(pending_id) is not int or pending_id < 1:
                    raise ValueError('Invalid import queue entry.')
                # Claim before creating anything. A repeated/concurrent save
                # cannot create a second template from this queue entry.
                claimed=PendingImport.objects.filter(pk=pending_id,owner=request.user,imported_at__isnull=True,dismissed=False).update(imported_at=timezone.now())
                if claimed!=1:
                    raise ValueError('This import is no longer pending. Reload the import queue.')
            t=Template.objects.create(owner=request.user,**normalize(data)); record(t)
            if pending_id is not None:
                PendingImport.objects.filter(pk=pending_id,owner=request.user).update(imported_template=t)
        return JsonResponse(serialize(t),status=201)
    items=Template.objects.filter(owner=request.user).order_by('-favorite','title')
    q=request.GET.get('q','').casefold().strip(); kind=request.GET.get('kind',''); tag=request.GET.get('tag','').casefold()
    result=[]
    for t in items:
        hay=' '.join([t.title,t.epic_name,*t.tags,*t.aliases,plain(t.content),plain(t.header)]).casefold()
        if q and q not in hay: continue
        if kind and kind!=t.kind: continue
        if tag and tag not in [x.casefold() for x in t.tags]: continue
        if request.GET.get('favorite')=='1' and not t.favorite: continue
        result.append(serialize(t))
    pending=PendingImport.objects.filter(owner=request.user,imported_at__isnull=True,dismissed=False).count()
    return JsonResponse({'items':result,'pending_imports':pending})

@api(['GET','PUT','DELETE'])
def detail(request,data,pk):
    t=own(request,pk)
    if request.method=='DELETE': t.delete(); return JsonResponse({'ok':True})
    if request.method=='PUT':
        with transaction.atomic(): replace(t,dict(data,original_source=t.original_source),data.get('version'))
    return JsonResponse(dict(serialize(t),revisions=list(t.revisions.order_by('-version').values('version','snapshot','created_at')),warnings=warnings(t.content),case_draft=case_draft_summary(request.user,t)))

@api(['POST'])
def restore(request,data,pk):
    t=own(request,pk)
    rev=t.revisions.filter(version=data.get('restore_version')).first()
    if not rev: raise ValueError('Revision not found.')
    with transaction.atomic(): replace(t,rev.snapshot,data.get('version'))
    return JsonResponse(serialize(t))

@api(['POST'])
def proposal(request,data):
    instruction=data.get('instruction','')
    if not isinstance(instruction,str) or not instruction.strip() or len(instruction)>10000: raise ValueError('Instructions required, maximum 10,000 characters.')
    mode=data.get('mode')
    if mode not in ['case','master']: raise ValueError('Invalid mode.')
    ids=data.get('ids',[])
    if not isinstance(ids,list) or not 1<=len(ids)<=10 or len(set(ids))!=len(ids): raise ValueError('Select 1–10 distinct templates.')
    selected=[own(request,pk) for pk in ids]
    if mode=='case' and (len(selected)!=1 or selected[0].kind not in ('operative','procedure')): raise ValueError('Select one operative or procedure template.')
    override='content' in data
    if mode=='master' and override and len(selected)!=1: raise ValueError('A content override applies to a single template only.')
    from .services import clean
    outputs=[]
    try:
        for t in selected:
            # master mode normally revises the saved template; an explicit content override (single
            # template only) lets the master editor improve the currently open, possibly-unsaved draft.
            source=clean(data.get('content','')) if (mode=='case' or override) else t.content
            result=propose(source,instruction)
            result.update(id=t.pk,version=t.version,source=source)
            outputs.append(result)
    except Exception:
        return JsonResponse({'error':'AI unavailable or returned an unsafe/invalid response. Your text is unchanged; continue manual editing.'},status=502)
    # Signed scope includes IDs and versions only, never case text or instructions.
    scope=signing.dumps({'user':request.user.pk,'mode':mode,'versions':{str(t.pk):t.version for t in selected}},salt='review')
    return JsonResponse({'proposals':outputs,'scope':scope,'provider':settings.AI_PROVIDER})

@api(['POST'])
def finalize(request,data):
    """Line-by-line case completion for a transient operative draft. Persists nothing."""
    from .services import clean, finalize_checklist, finalize_apply, _fill_sentences
    content=clean(data.get('content',''))
    if not plain(content): raise ValueError('No narrative to finalize.')
    if data.get('step')=='questions':
        try:
            return JsonResponse({'items':finalize_checklist(content),'provider':settings.AI_PROVIDER})
        except Exception:
            # AI checklist failed; still return the raw placeholders so the surgeon can work manually.
            fills=[{'context':f['context'],'token':f['token'],'question':'What value replaces '+f['token']+' here?','placeholder':True} for f in _fill_sentences(content)]
            return JsonResponse({'items':fills,'provider':settings.AI_PROVIDER,'degraded':True})
    answers=data.get('answers')
    if not isinstance(answers,list) or not 1<=len(answers)<=60: raise ValueError('Provide 1–60 answered items.')
    norm=[]
    for a in answers:
        if not isinstance(a,dict): raise ValueError('Invalid answer item.')
        ans=str(a.get('answer','')).strip()
        if ans: norm.append({'question':str(a.get('question',''))[:2000],'answer':ans[:5000]})
    if not norm: raise ValueError('Answer at least one item.')
    try:
        result=finalize_apply(content,norm)
    except Exception:
        return JsonResponse({'error':'AI unavailable or returned an unsafe/invalid response. Your text is unchanged; continue manual editing.'},status=502)
    return JsonResponse({'proposal':dict(result,source=content),'provider':settings.AI_PROVIDER})

@api(['POST'])
def grammar(request,data):
    """Mechanical grammar/punctuation pass over template content before a master save."""
    from .services import clean, grammar_pass
    content=clean(data.get('content',''))
    if not plain(content): raise ValueError('No content to check.')
    try:
        result=grammar_pass(content)
    except Exception:
        return JsonResponse({'error':'Grammar check unavailable or returned an unsafe response. You can save without it.'},status=502)
    return JsonResponse({'proposal':dict(result,source=content),'provider':settings.AI_PROVIDER})

@api(['POST'])
def mod22(request,data):
    """Explicit, surgeon-initiated modifier-22 statement for a transient case draft."""
    from .services import clean, mod22_statement
    content=clean(data.get('content',''))
    if not plain(content): raise ValueError('No narrative to add to.')
    factors=str(data.get('factors','')).strip()[:10000]
    reasons=data.get('reasons',[])
    if not isinstance(reasons,list) or any(not isinstance(r,str) for r in reasons) or len(reasons)>30: raise ValueError('Invalid reasons.')
    reasons=[r.strip()[:300] for r in reasons if r.strip()]
    template_text=''
    tid=data.get('template_id')
    if tid is not None:
        template_text=clean(own(request,tid).content)[:12000]
    try:
        result=mod22_statement(content,factors,template_text,reasons)
    except ValueError:
        raise
    except Exception:
        return JsonResponse({'error':'Modifier-22 draft unavailable or returned an unsafe response. Your text is unchanged.'},status=502)
    return JsonResponse({'proposal':dict(result,source=content),'provider':settings.AI_PROVIDER})

@api(['POST'])
def approve(request,data):
    scope=signing.loads(data['scope'],salt='review',max_age=3600)
    if scope['user']!=request.user.pk or scope['mode']!='master': raise ValueError('Invalid review scope.')
    pk=str(data['id'])
    if pk not in scope['versions']: raise ValueError('Template is outside the selected scope.')
    t=own(request,pk)
    from .services import clean
    content=clean(data['content'])
    if tokens(t.content)!=tokens(content) and data.get('review_tokens') is not True: raise ValueError('Protected tokens changed. Explicit token review is required.')
    with transaction.atomic(): replace(t,dict(snapshot(t),content=content),scope['versions'][pk])
    return JsonResponse(serialize(t))

@api(['GET'])
def export_data(request,data):
    items=[]
    for t in Template.objects.filter(owner=request.user):
        items.append(dict(serialize(t),revisions=list(t.revisions.order_by('version').values('version','snapshot','created_at'))))
    response=JsonResponse({'format':'smartphrase-v1','items':items})
    response['Content-Disposition']='attachment; filename="smartphrase-backup.json"'
    return response

@api(['POST'])
def import_data(request,data):
    if data.get('format')!='smartphrase-v1' or not isinstance(data.get('items'),list) or len(data['items'])>500: raise ValueError('Invalid backup (maximum 500 templates).')
    from django.utils.dateparse import parse_datetime
    def date(value):
        result=parse_datetime(value)
        if not result or result.tzinfo is None: raise ValueError('Invalid timestamp.')
        return result
    with transaction.atomic():
        for item in data['items']:
            values=normalize(item); revisions=item['revisions']; version=item['version']
            if not isinstance(version,int) or not isinstance(revisions,list) or len(revisions)!=version or [r['version'] for r in revisions]!=list(range(1,version+1)): raise ValueError('Invalid revision sequence.')
            if normalize(revisions[-1]['snapshot'])!=values: raise ValueError('Latest revision does not match template.')
            t=Template.objects.create(owner=request.user,version=version,**values)
            Template.objects.filter(pk=t.pk).update(created_at=date(item['created_at']),updated_at=date(item['updated_at']))
            for rev in revisions:
                r=Revision.objects.create(template=t,version=rev['version'],snapshot=normalize(rev['snapshot']))
                Revision.objects.filter(pk=r.pk).update(created_at=date(rev['created_at']))
    return JsonResponse({'imported':len(data['items'])})

def draft_row(d):
    return {'id':d.pk,'template_id':d.template_id,'template_title':d.template.title,'kind':d.kind,
            'label':d.label,'base_version':d.base_version,'stale_base':d.stale_base,'updated_at':d.updated_at.isoformat()}

def draft_full(d):
    return dict(draft_row(d),content=d.content,template_version=d.template.version)

def case_draft_summary(user,t):
    """Compact resume marker for the template detail response, or None. Prunes expired rows first."""
    CaseDraft.prune(user)
    d=CaseDraft.objects.filter(owner=user,template=t).first()
    return draft_row(d) if d else None

@api(['GET','POST'])
def drafts(request,data):
    """Opt-in resumable case drafts. One row per master template; an explicit save overwrites it."""
    CaseDraft.prune(request.user)
    if request.method=='POST':
        from .services import clean
        tid=data.get('template_id')
        if type(tid) is not int or tid<1: raise ValueError('A template is required.')
        t=own(request,tid)
        if t.kind not in ('operative','procedure'): raise ValueError('Only operative and procedure cases can be saved.')
        content=clean(data.get('content',''))
        if not plain(content): raise ValueError('There is nothing to save yet.')
        label=str(data.get('label','')).strip()[:200]
        d,_=CaseDraft.objects.update_or_create(owner=request.user,template=t,
            defaults={'kind':t.kind,'base_version':t.version,'content':content,'label':label})
        d.template=t  # avoid a refetch for stale_base/title
        return JsonResponse(draft_full(d))
    rows=CaseDraft.objects.filter(owner=request.user).select_related('template')
    return JsonResponse({'items':[draft_row(d) for d in rows]})

@api(['GET','DELETE'])
def draft_item(request,data,pk):
    CaseDraft.prune(request.user)
    d=CaseDraft.objects.select_related('template').get(pk=pk,owner=request.user)
    if request.method=='DELETE':
        d.delete(); return JsonResponse({'ok':True})
    return JsonResponse(draft_full(d))

@api(['GET'])
def status(request,data):
    from .services import ai_configured, ai_base_url
    from urllib.parse import urlparse
    return JsonResponse({'provider':settings.AI_PROVIDER,'model':settings.AI_MODEL,'endpoint':urlparse(ai_base_url()).netloc,'configured':ai_configured(),'username':request.user.username})

def pending_row(row):
    return {'id':row.pk,'name':row.name,'text':row.text,'html':row.html,'flags':row.flags,'chars':len(row.text),'source_name':row.source_name,'batch':row.batch,'order':row.order}

def pending_counts(user):
    base=PendingImport.objects.filter(owner=user)
    return {'pending':base.filter(imported_at__isnull=True,dismissed=False).count(),
            'imported':base.filter(imported_at__isnull=False).count(),
            'dismissed':base.filter(imported_at__isnull=True,dismissed=True).count()}

def import_pdf(request):
    # Multipart upload, so this bypasses the JSON @api wrapper but keeps auth, method and CSRF checks.
    if not request.user.is_authenticated: return JsonResponse({'error':'Login required.'},status=401)
    if request.method!='POST': return JsonResponse({'error':'Method not allowed.'},status=405)
    import hashlib, uuid
    from django.utils.text import get_valid_filename
    from .pdfimport import parse_pdf, MAX_PDF_BYTES
    upload=request.FILES.get('file')
    if not upload: return JsonResponse({'error':'Attach a PDF file.'},status=400)
    if upload.size>MAX_PDF_BYTES: return JsonResponse({'error':'The PDF exceeds the 25 MB import limit.'},status=400)
    source_name=get_valid_filename(upload.name or 'upload.pdf')[:200]
    data=upload.read()
    try:
        segments=parse_pdf(data)
    except ValueError as e:
        return JsonResponse({'error':str(e)},status=400)
    finally:
        del data  # the PDF bytes are never persisted or logged
    # Persist the parsed phrases as an owner-scoped import queue; dedupe against
    # everything this owner has ever queued so re-uploading the same PDF is a no-op.
    seen={h for h in PendingImport.objects.filter(owner=request.user).values_list('text_hash',flat=True)}
    batch=uuid.uuid4().hex; added=0; skipped=0
    with transaction.atomic():
        for i,seg in enumerate(segments):
            h=hashlib.sha256((seg['name']+'\x00'+seg['text']).encode('utf-8')).hexdigest()
            if h in seen: skipped+=1; continue
            seen.add(h)
            PendingImport.objects.create(owner=request.user,batch=batch,source_name=source_name,name=seg['name'][:200],
                text=seg['text'],html=seg['html'],flags=seg['flags'],order=i,text_hash=h)
            added+=1
    return JsonResponse({'added':added,'skipped':skipped,'counts':pending_counts(request.user)})

@api(['GET'])
def imports_list(request,data):
    rows=PendingImport.objects.filter(owner=request.user,imported_at__isnull=True)
    rows=rows.filter(dismissed=(request.GET.get('dismissed')=='1'))
    return JsonResponse({'items':[pending_row(r) for r in rows],'counts':pending_counts(request.user)})

@api(['POST'])
def import_resolve(request,data,pk):
    row=PendingImport.objects.get(pk=pk,owner=request.user)
    action=data.get('action')
    if action=='dismiss':
        row.dismissed=True; row.save(update_fields=['dismissed'])
    elif action=='restore':
        row.dismissed=False; row.imported_at=None; row.imported_template=None
        row.save(update_fields=['dismissed','imported_at','imported_template'])
    elif action=='imported':
        tid=data.get('template_id')
        if type(tid) is not int or tid < 1: raise ValueError('A saved template is required.')
        row.imported_template=own(request,tid)
        row.imported_at=timezone.now(); row.dismissed=False
        row.save(update_fields=['imported_at','imported_template','dismissed'])
    else:
        raise ValueError('Unknown action.')
    return JsonResponse({'ok':True,'counts':pending_counts(request.user)})

@api(['POST'])
def imports_resolve_all(request,data):
    """Bulk skip / restore every not-yet-imported queue row for this user."""
    rows=PendingImport.objects.filter(owner=request.user,imported_at__isnull=True)
    action=data.get('action')
    if action=='dismiss':
        updated=rows.filter(dismissed=False).update(dismissed=True)
    elif action=='restore':
        updated=rows.filter(dismissed=True).update(dismissed=False)
    else:
        raise ValueError('Unknown action.')
    return JsonResponse({'updated':updated,'counts':pending_counts(request.user)})

@api(['POST'])
def imports_clear(request,data):
    scope=data.get('scope','resolved')
    rows=PendingImport.objects.filter(owner=request.user)
    if scope=='resolved': rows=rows.filter(Q(imported_at__isnull=False)|Q(dismissed=True))
    elif scope=='batch':
        if not data.get('batch'): raise ValueError('A batch is required.')
        rows=rows.filter(batch=data['batch'])
    elif scope!='all': raise ValueError('Unknown scope.')
    deleted=rows.delete()[0]
    return JsonResponse({'deleted':deleted,'counts':pending_counts(request.user)})
