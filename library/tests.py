import json
from datetime import timedelta
from unittest.mock import patch
from django.test import TestCase, Client, override_settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.utils import timezone
from .models import Template, Revision, PendingImport, CaseDraft
from .services import tokens, clean, propose

class Workflows(TestCase):
    def setUp(self):
        cache.clear()
        self.user=get_user_model().objects.create_user('owner',password='synthetic-test-password')
        self.client.force_login(self.user)
        self.a=self.create('Synthetic prostatectomy',kind='operative',epic_name='ASOPNSPRALP',tags=['robot'],aliases=['RALP','radical prostatectomy'],header='<p>@NAME@ @MRN@</p>',content='<h2>Indication for Procedure</h2><p>@AGE@ *** {UNFAMILIAR:987} @ODD_TOKEN@</p><p>No complications.</p>')
        self.b=self.create('Counseling',content='<p>Transperineal discussion</p>',aliases=['TP','TR'])
    def call(self,path,data,method='post'):
        return getattr(self.client,method)('/api/'+path,data=json.dumps(data),content_type='application/json')
    def create(self,title,**kwargs):
        r=self.call('templates/',dict(title=title,content='<p>Source</p>',**{k:v for k,v in kwargs.items() if k!='content'})|({'content':kwargs['content']} if 'content' in kwargs else {}))
        self.assertEqual(r.status_code,201,r.content)
        return r.json()
    def proposal(self,mode='master',**kw):
        return self.call('propose/',dict(mode=mode,ids=[self.a['id']],instruction='Significant periprostatic inflammation and scarring made dissection difficult.',**kw))
    def test_search_all_fields(self):
        for q in ['prostatectomy','robot','RALP','radical prostatectomy','ASOPNSPRALP','UNFAMILIAR']:
            self.assertEqual(self.client.get('/api/templates/',{'q':q}).json()['items'][0]['id'],self.a['id'])
        self.assertEqual(self.client.get('/api/templates/',{'q':'TP'}).json()['items'][0]['id'],self.b['id'])
        self.assertEqual(len(self.client.get('/api/templates/',{'kind':'operative','tag':'robot'}).json()['items']),1)
    def test_auth_and_ownership(self):
        guest=Client()
        for endpoint in ['templates/','export/','status/']:
            self.assertEqual(guest.get('/api/'+endpoint).status_code,401)
        self.assertEqual(guest.post('/api/propose/',data='{}',content_type='application/json').status_code,401)
        self.client.force_login(get_user_model().objects.create_user('other'))
        self.assertEqual(self.client.get('/api/templates/').json()['items'],[])
        self.assertEqual(self.client.get(f"/api/templates/{self.a['id']}/").status_code,404)
    def test_csrf(self):
        c=Client(enforce_csrf_checks=True);c.force_login(self.user)
        self.assertEqual(c.post('/api/templates/',data='{}',content_type='application/json').status_code,403)
    def test_case_ephemeral_and_header_excluded(self):
        before=list(Template.objects.values()); history=list(Revision.objects.values())
        with patch('library.views.propose',wraps=propose) as provider:
            r=self.proposal('case',content=self.a['content'])
            self.assertEqual(r.status_code,200)
            self.assertNotIn('@MRN@',provider.call_args.args[0])
            self.assertNotIn('@NAME@',r.json()['proposals'][0]['content'])
        self.assertEqual(before,list(Template.objects.values()))
        self.assertEqual(history,list(Revision.objects.values()))
        self.assertNotIn('scarring',str(list(self.client.session.items())))
        r2=self.call('approve/',{'scope':r.json()['scope'],'id':self.a['id'],'content':'bad'})
        self.assertEqual(r2.status_code,400)
    def test_note_types_accepted_filtered_and_validated(self):
        p=self.create('Office cystoscopy',kind='procedure',epic_name='ASPROCCYSTO',content='<p>Findings: [[Bladder: normal | trabeculation | mass]] EBL [[EBL: minimal | *** mL]].</p>')
        lib=self.create('TURP evidence',kind='library',epic_name='ASCLINICPLANTURP',content='<p>Risks and benefits were discussed.</p>')
        self.assertEqual(self.client.get(f"/api/templates/{p['id']}/").json()['kind'],'procedure')
        self.assertEqual(self.client.get(f"/api/templates/{lib['id']}/").json()['kind'],'library')
        self.assertEqual({t['id'] for t in self.client.get('/api/templates/',{'kind':'procedure'}).json()['items']},{p['id']})
        self.assertEqual(self.call('templates/',{'title':'Bad','kind':'nonsense','content':'<p>x</p>'}).status_code,400)
        return p

    def test_case_proposal_accepts_procedure_rejects_library(self):
        p=self.test_note_types_accepted_filtered_and_validated()
        ok=self.call('propose/',{'mode':'case','ids':[p['id']],'instruction':'Assemble into prose.','content':'<p>Bladder trabeculation. EBL minimal.</p>'})
        self.assertEqual(ok.status_code,200,ok.content)
        self.assertTrue(ok.json()['proposals'][0]['content'])
        lib=self.create('Lib2',kind='library',content='<p>x</p>')
        bad=self.call('propose/',{'mode':'case','ids':[lib['id']],'instruction':'x','content':'<p>x</p>'})
        self.assertEqual(bad.status_code,400)

    def test_scope_reject_approve_restore_and_stale(self):
        result=self.proposal().json()
        self.assertEqual(Revision.objects.count(),2) # proposing/rejecting makes no persistent change
        outside=self.call('approve/',{'scope':result['scope'],'id':self.b['id'],'content':'unselected'})
        self.assertEqual(outside.status_code,400)
        payload={'scope':result['scope'],'id':self.a['id'],'content':result['proposals'][0]['content']}
        approved=self.call('approve/',payload)
        self.assertEqual(approved.status_code,200,approved.content)
        self.assertEqual(approved.json()['version'],2)
        self.assertEqual(Template.objects.get(pk=self.b['id']).version,1)
        self.assertEqual(self.call('approve/',payload).status_code,400)
        restored=self.call(f"templates/{self.a['id']}/restore/",{'restore_version':1,'version':2})
        self.assertEqual(restored.json()['content'],self.a['content'])
        self.assertEqual(restored.json()['version'],3)
    def test_master_mode_content_override_for_unsaved_editor_draft(self):
        # The master editor's "ask AI to improve this note" sends the currently open (possibly
        # unsaved) draft rather than the last-saved revision.
        draft='<p>@AGE@ *** unsaved editor draft</p>'
        self.assertNotEqual(draft,self.a['content'])
        before=list(Template.objects.values())
        r=self.proposal(content=draft)
        self.assertEqual(r.status_code,200,r.content)
        self.assertEqual(r.json()['proposals'][0]['source'],draft)
        self.assertEqual(before,list(Template.objects.values()))  # persists nothing
        # A content override naming more than one template is ambiguous and rejected.
        bad=self.call('propose/',{'mode':'master','ids':[self.a['id'],self.b['id']],'instruction':'x','content':draft})
        self.assertEqual(bad.status_code,400)
        # Without an override, master mode still revises the saved template content (batch update).
        r2=self.proposal()
        self.assertEqual(r2.json()['proposals'][0]['source'],self.a['content'])
    def test_tokens_and_explicit_review(self):
        src='<p>@NAME@ @ODD_NEW@ {UNKNOWN:abc} *** {a|b} @NAME@</p>'
        self.assertEqual(sum(tokens(src).values()),6)
        r=self.proposal().json()
        payload={'scope':r['scope'],'id':self.a['id'],'content':'<p>tokens removed</p>'}
        self.assertEqual(self.call('approve/',payload).status_code,400)
        payload['review_tokens']=True
        self.assertEqual(self.call('approve/',payload).status_code,200)
    def test_failure_preserves_original(self):
        before=list(Template.objects.values())
        with patch('library.views.propose',side_effect=TimeoutError('private-case-secret')):
            response=self.proposal()
        self.assertEqual(response.status_code,502)
        self.assertNotIn('private-case-secret',response.content.decode())
        self.assertEqual(before,list(Template.objects.values()))
    def test_mock_questions_conflicts_no_time(self):
        r=self.proposal().json()['proposals'][0]
        self.assertTrue(r['questions'])
        self.assertTrue(any('complications' in w for w in r['warnings']))
        self.assertNotRegex(r['content'],r'\d+ minutes|modifier')
        self.assertEqual(tokens(r['content']),tokens(self.a['content']))

    def test_finalize_line_by_line(self):
        before=list(Template.objects.values()); hist=list(Revision.objects.values())
        q=self.call('finalize/',{'content':self.a['content'],'step':'questions'})
        self.assertEqual(q.status_code,200,q.content)
        items=q.json()['items']
        self.assertTrue(any(it['placeholder'] and '***' in (it['context'] or '') for it in items))  # *** fill-in surfaced with its sentence
        self.assertTrue(any(not it['placeholder'] for it in items))                                  # plus a non-*** review question
        self.assertEqual([it['placeholder'] for it in items],sorted((it['placeholder'] for it in items)))  # review items first, then placeholders
        a=self.call('finalize/',{'content':self.a['content'],'answers':[{'question':'Fill-in','answer':'Floseal was applied to the pedicle.'}]})
        self.assertEqual(a.status_code,200,a.content)
        p=a.json()['proposal']
        self.assertEqual(set(p)>= {'content','summary','questions','warnings','source'},True)
        self.assertIn('Floseal',p['content'])
        self.assertNotIn('***',p['content'])            # the *** placeholder was consumed
        self.assertEqual(before,list(Template.objects.values()))   # persists nothing
        self.assertEqual(hist,list(Revision.objects.values()))
        self.assertNotIn('Floseal',str(list(self.client.session.items())))

    def test_finalize_validation_and_auth(self):
        self.assertEqual(self.call('finalize/',{'content':'','step':'questions'}).status_code,400)
        self.assertEqual(self.call('finalize/',{'content':self.a['content'],'answers':[]}).status_code,400)
        self.assertEqual(self.call('finalize/',{'content':self.a['content'],'answers':[{'answer':'  '}]}).status_code,400)
        self.assertEqual(Client().post('/api/finalize/',data='{}',content_type='application/json').status_code,401)

    def test_finalize_surfaces_all_placeholder_types(self):
        items=self.call('finalize/',{'content':self.a['content'],'step':'questions'}).json()['items']
        toks={it['token'] for it in items if it['placeholder']}
        self.assertEqual(toks,{'@AGE@','***','{UNFAMILIAR:987}','@ODD_TOKEN@'})  # not just ***

    def test_grammar_pass_mock_and_endpoint(self):
        before=list(Template.objects.values())
        r=self.call('grammar/',{'content':self.a['content']})
        self.assertEqual(r.status_code,200,r.content)
        p=r.json()['proposal']
        self.assertEqual(p['content'],self.a['content'])          # mock leaves text unchanged
        self.assertEqual(p['source'],self.a['content'])
        self.assertTrue(p['questions'])                            # mock disclaimer present
        self.assertEqual(before,list(Template.objects.values()))   # persists nothing
        self.assertEqual(self.call('grammar/',{'content':''}).status_code,400)
        self.assertEqual(Client().post('/api/grammar/',data='{}',content_type='application/json').status_code,401)

    @override_settings(AI_PROVIDER='gemini',AI_API_KEY='k',AI_MODEL='gemini-2.5-flash')
    def test_grammar_pass_keeps_tokens(self):
        from library.services import grammar_pass
        src='<p>@AGE@ male,the dissection  was difficult .No complications</p>'
        fixed={'content':'<p>@AGE@ male, the dissection was difficult. No complications.</p>','summary':'Fixed spacing and punctuation.','questions':[]}
        with patch('library.services.httpx.Client') as client:
            client.return_value.__enter__.return_value.post.return_value.json.return_value={'choices':[{'message':{'content':json.dumps(fixed)}}]}
            out=grammar_pass(src)
        self.assertIn('@AGE@',out['content'])
        self.assertEqual(out['token_changes'],False)              # tokens unchanged -> no flag

    def test_mod22_mock_placement_and_validation(self):
        before=list(Template.objects.values())
        r=self.call('mod22/',{'content':self.a['content'],'factors':'dense adhesions from prior open surgery; morbid obesity'})
        self.assertEqual(r.status_code,200,r.content)
        p=r.json()['proposal']
        self.assertIn('Unusual Procedure:',p['content'])                              # CMS-mandated label
        self.assertGreater(p['content'].index('Unusual Procedure'),p['content'].index('Indication for Procedure'))  # appended at the end
        self.assertRegex(p['content'],r'</p>\s*<p>\s*</p>\s*<p>\s*<strong>Unusual Procedure')  # blank line before the statement
        self.assertTrue(p['content'].rstrip().endswith('</p>'))
        self.assertTrue(any('coding eligibility' in w for w in p['warnings']))
        self.assertEqual(p['source'],self.a['content'])
        self.assertEqual(before,list(Template.objects.values()))          # persists nothing
        self.assertEqual(self.call('mod22/',{'content':self.a['content']}).status_code,400)   # no factors, no template
        self.assertEqual(Client().post('/api/mod22/',data='{}',content_type='application/json').status_code,401)

    @override_settings(AI_PROVIDER='gemini',AI_API_KEY='k',AI_MODEL='gemini-2.5-flash')
    def test_mod22_forces_unusual_procedure_label_without_template(self):
        from library.services import mod22_statement
        src='<h2>Indication for Procedure</h2><p>@AGE@ ***</p>'
        # model omits the mandated label -> it is prepended
        no_label={'statement':'<p>This case involved dense adhesions requiring substantially more work than usual.</p>','summary':'x','questions':[]}
        with patch('library.services.httpx.Client') as client:
            client.return_value.__enter__.return_value.post.return_value.json.return_value={'choices':[{'message':{'content':json.dumps(no_label)}}]}
            out=mod22_statement(src,'dense adhesions from a prior operation')
        self.assertIn('<strong>Unusual Procedure:</strong>',out['content'])
        self.assertGreater(out['content'].index('Unusual Procedure'),out['content'].index('Indication for Procedure'))

    def test_mod22_uses_template_and_selected_reasons(self):
        tpl=self.create('Mod22 RALP',kind='other',epic_name='ASMOD22RALP',content='<p>This procedure was substantially greater than typically required due to: [dense periprostatic adhesions], [prior radiation], [extensive lysis of adhesions].</p>')
        # picking a reason but no free-text factors is allowed
        r=self.call('mod22/',{'content':self.a['content'],'factors':'','template_id':tpl['id'],'reasons':['dense periprostatic adhesions']})
        self.assertEqual(r.status_code,200,r.content)
        self.assertIn('dense periprostatic adhesions',r.json()['proposal']['content'])   # selected reason carried through
        # neither a factor nor a reason -> 400
        self.assertEqual(self.call('mod22/',{'content':self.a['content'],'template_id':tpl['id'],'reasons':[]}).status_code,400)

    @override_settings(AI_PROVIDER='gemini',AI_API_KEY='k',AI_MODEL='gemini-2.5-flash')
    def test_mod22_allows_supplied_time_rejects_invented(self):
        from library.services import mod22_statement
        src='<h2>Indication for Procedure</h2><p>@AGE@ ***</p>'
        ok={'content':'<p>Modifier 22: an additional 75 minutes of adhesiolysis was required due to dense adhesions.</p>'+src,'summary':'Added modifier-22 paragraph.','questions':[]}
        with patch('library.services.httpx.Client') as client:
            client.return_value.__enter__.return_value.post.return_value.json.return_value={'choices':[{'message':{'content':json.dumps(ok)}}]}
            out=mod22_statement(src,'an additional 75 minutes of adhesiolysis, dense adhesions')
        self.assertIn('75 minutes',out['content'])                # figure the surgeon supplied is allowed
        bad={'content':'<p>Modifier 22: this took an extra 200 minutes.</p>'+src,'summary':'x','questions':[]}
        with patch('library.services.httpx.Client') as client:
            client.return_value.__enter__.return_value.post.return_value.json.return_value={'choices':[{'message':{'content':json.dumps(bad)}}]}
            with self.assertRaises(ValueError): mod22_statement(src,'dense adhesions')   # 200 minutes not supplied -> rejected
    def test_backup_roundtrip_and_atomic_failure(self):
        backup=self.client.get('/api/export/').json()
        response=self.call('import/',backup)
        self.assertEqual(response.status_code,200,response.content)
        after=self.client.get('/api/export/').json()['items']
        for old,new in zip(backup['items'],after[2:]):
            old.pop('id');new.pop('id');self.assertEqual(old,new)
        backup['items'][1]['revisions']=[]
        count=Template.objects.count()
        self.assertEqual(self.call('import/',backup).status_code,400)
        self.assertEqual(Template.objects.count(),count)
    def test_safe_import_and_original(self):
        original='<p onclick="alert(1)">@NEW@</p><img src=x onerror="alert(1)"><script>alert(1)</script>'
        result=self.create('Unsafe source',content=original,original_source=original)
        self.assertNotIn('onclick',result['content']);self.assertNotIn('<script',result['content']);self.assertNotIn('<img',result['content'])
        self.assertEqual(result['original_source'],original)
        self.assertIn('@NEW@',result['content'])
    def test_rate_limit_and_cache_headers(self):
        self.assertIn('no-store',self.client.get('/api/templates/')['Cache-Control'])
        self.assertEqual(self.client.get('/login/')['Referrer-Policy'],'same-origin')
        for _ in range(20): self.call('propose/',{})
        self.assertEqual(self.call('propose/',{}).status_code,429)
    @override_settings(AI_PROVIDER='compatible',AI_API_KEY='test',AI_MODEL='test',AI_BASE_URL='https://example.invalid/v1')
    def test_malformed_and_unsupported_claims(self):
        for output in [{'content':'<p>Added 30 minutes</p>','summary':'change','questions':[]},{'content':'bad'},{'content':'<p>modifier 22</p>','summary':'change','questions':[]}]:
            with patch('library.services.httpx.Client') as client:
                client.return_value.__enter__.return_value.post.return_value.json.return_value={'choices':[{'message':{'content':json.dumps(output)}}]}
                with self.assertRaises(ValueError):propose('<p>Difficult dissection.</p>','Reflect scarring.')

    def test_ai_configured_and_base_url(self):
        from library.services import ai_configured, ai_base_url, OPENROUTER_URL, GEMINI_URL
        self.assertTrue(ai_configured())  # default mock
        with override_settings(AI_PROVIDER='openrouter',AI_API_KEY='',AI_MODEL='x'):
            self.assertFalse(ai_configured())
        with override_settings(AI_PROVIDER='openrouter',AI_API_KEY='k',AI_MODEL='anthropic/claude-sonnet-4',AI_BASE_URL=''):
            self.assertTrue(ai_configured()); self.assertEqual(ai_base_url(),OPENROUTER_URL)
        with override_settings(AI_PROVIDER='gemini',AI_API_KEY='k',AI_MODEL='gemini-2.5-flash',AI_BASE_URL=''):
            self.assertTrue(ai_configured()); self.assertEqual(ai_base_url(),GEMINI_URL)
        with override_settings(AI_PROVIDER='gemini',AI_API_KEY='k',AI_MODEL='gemini-2.5-flash',AI_BASE_URL='https://proxy.example/v1'):
            self.assertEqual(ai_base_url(),'https://proxy.example/v1')  # explicit base still wins
        with override_settings(AI_PROVIDER='compatible',AI_API_KEY='k',AI_MODEL='m',AI_BASE_URL=''):
            self.assertFalse(ai_configured())

    @override_settings(AI_PROVIDER='gemini',AI_API_KEY='g',AI_MODEL='gemini-2.5-flash')
    def test_gemini_call_shape(self):
        good={'content':'<p>@AGE@ *** revised.</p>','summary':'ok','questions':[]}
        with patch('library.services.httpx.Client') as client:
            post=client.return_value.__enter__.return_value.post
            post.return_value.json.return_value={'choices':[{'message':{'content':json.dumps(good)}}]}
            propose('<p>@AGE@ ***</p>','Reflect scarring; no time added.')
        url,kw=post.call_args[0],post.call_args[1]
        self.assertEqual(url[0],'https://generativelanguage.googleapis.com/v1beta/openai/chat/completions')
        self.assertEqual(kw['headers']['Authorization'],'Bearer g')
        self.assertNotIn('HTTP-Referer',kw['headers'])  # openrouter-only

    def test_parse_json_tolerates_fences_and_prose(self):
        from library.services import _parse_json
        self.assertEqual(_parse_json('```json\n{"a": 1}\n```'),{'a':1})
        self.assertEqual(_parse_json('Sure, here you go:\n{"a": 2}\nthanks'),{'a':2})
        with self.assertRaises(ValueError):_parse_json('no json here')

    @override_settings(AI_PROVIDER='openrouter',AI_API_KEY='k',AI_MODEL='anthropic/claude-sonnet-4',AI_APP_URL='https://smartphrase.example')
    def test_openrouter_call_shape_and_fenced_response(self):
        good={'content':'<p>@AGE@ with periprostatic scarring made dissection difficult. ***</p>','summary':'reflected scarring','questions':[]}
        with patch('library.services.httpx.Client') as client:
            post=client.return_value.__enter__.return_value.post
            post.return_value.json.return_value={'choices':[{'message':{'content':'```json\n'+json.dumps(good)+'\n```'}}]}
            result=propose('<p>@AGE@ with indication ***</p>','Reflect periprostatic scarring; do not add time.')
        url,kw=post.call_args[0],post.call_args[1]
        self.assertEqual(url[0],'https://openrouter.ai/api/v1/chat/completions')
        self.assertEqual(kw['headers']['Authorization'],'Bearer k')
        self.assertEqual(kw['headers']['HTTP-Referer'],'https://smartphrase.example')
        self.assertNotIn('response_format',kw['json'])
        self.assertIn('scarring',result['content']); self.assertEqual(result['token_changes'],False)


def tiny_pdf(lines):
    """Minimal single-page PDF whose text pypdf can extract. Test fixture only."""
    import io
    def esc(s): return s.replace('\\','\\\\').replace('(','\\(').replace(')','\\)')
    content='BT /F1 11 Tf 54 760 Td 13 TL\n'+''.join('(%s) Tj T*\n'%esc(l) for l in lines)+'ET'
    cb=content.encode('latin-1')
    objs=[b'<< /Type /Catalog /Pages 2 0 R >>',
          b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
          b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
          b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
          b'<< /Length %d >>\nstream\n'%len(cb)+cb+b'\nendstream']
    out=io.BytesIO(); out.write(b'%PDF-1.4\n'); offs=[]
    for i,o in enumerate(objs,1):
        offs.append(out.tell()); out.write(b'%d 0 obj\n'%i+o+b'\nendobj\n')
    xref=out.tell(); out.write(b'xref\n0 %d\n0000000000 65535 f \n'%(len(objs)+1))
    for off in offs: out.write(b'%010d 00000 n \n'%off)
    out.write(b'trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF'%(len(objs)+1,xref))
    return out.getvalue()


class PdfImport(TestCase):
    # An unnamed lead segment, two named phrases, a wrapped ALL-CAPS content line
    # that must NOT be treated as a new phrase, an age line, and a token-free phrase.
    LINES=['UROLOGY: Established Patient Follow-Up','Patient: @NAME@','@NAME@ is a 62 year old man.',
           ' ','ASLIBTPVSTR','Transperineal versus transrectal biopsy counseling.','Risks discussed ***.',
           ' ','ASDCINSTRUCTIONSRALP','DISCHARGE INSTRUCTIONS FOLLOWING ROBOTIC ASSISTED RADICAL ',
           'PROSTATECTOMY','- You may shower','- Drink plenty of water',
           ' ','ASLIBPLAINTEXT','This phrase has no Epic tokens at all.']

    def setUp(self):
        cache.clear()
        self.user=get_user_model().objects.create_user('owner',password='synthetic-test-password')
        self.client.force_login(self.user)
        self.b=self.client.post('/api/templates/',data=json.dumps({'title':'Existing','content':'<p>x</p>'}),content_type='application/json').json()

    def test_split_segments_and_flags(self):
        from .pdfimport import split_segments, flags_for
        segs=split_segments('\n'.join(self.LINES))
        self.assertEqual([s['name'] for s in segs],[None,'ASLIBTPVSTR','ASDCINSTRUCTIONSRALP','ASLIBPLAINTEXT'])
        self.assertIn('Established Patient Follow-Up',segs[0]['text'])
        # Wrapped ALL-CAPS content line stays inside its phrase, not split off.
        self.assertIn('PROSTATECTOMY',segs[2]['text'])
        self.assertIn('You may shower',segs[2]['text'])
        self.assertTrue(any('fixed patient age' in f.lower() for f in flags_for(None,segs[0]['text'])))
        self.assertTrue(any('no epic tokens' in f.lower() for f in flags_for('ASLIBPLAINTEXT',segs[3]['text'])))
        self.assertTrue(any('no smartphrase name' in f.lower() for f in flags_for(None,segs[0]['text'])))

    def test_text_to_html_is_conservative_and_escaped(self):
        from .pdfimport import text_to_html
        self.assertEqual(text_to_html('- a\n- b'),'<ul><li>a</li><li>b</li></ul>')
        html=text_to_html('Indication for Procedure:\nLine two\n\nNext para <script>alert(1)</script>')
        # "Label:" lines stay their own <p> so the Epic-header split lands on a real boundary.
        self.assertIn('<p>Indication for Procedure:</p>',html)
        self.assertIn('<p>Line two</p>',html)
        self.assertIn('&lt;script&gt;',html); self.assertNotIn('<script>',html)

    def test_text_to_html_reflows_epic_hard_wrap(self):
        from .pdfimport import text_to_html
        # Epic hard-wraps one prose paragraph across several lines mid-sentence.
        wrapped=('The patient was brought to the operating room where a timeout was performed. Ancef was given for\n'
                 'antibiotic\n'
                 'prophylaxis. The patient was then prepped and draped in the usual sterile fashion.')
        self.assertEqual(
            text_to_html(wrapped),
            '<p>The patient was brought to the operating room where a timeout was performed. '
            'Ancef was given for antibiotic prophylaxis. The patient was then prepped and '
            'draped in the usual sterile fashion.</p>')
        # Label lines, numbered lines and blank-line breaks are preserved, not merged.
        html=text_to_html('Surgeon: A B, MD\nAssistant(s): C D PA-C\n\nSpecimens:\n1. Renal mass\n2. ***')
        self.assertIn('<p>Surgeon: A B, MD</p>',html)
        self.assertIn('<p>Assistant(s): C D PA-C</p>',html)
        self.assertIn('<p>Specimens:</p>',html)
        self.assertIn('<li>Renal mass</li>',html)
        self.assertNotIn('Surgeon: A B, MD Assistant',html)

    def upload(self,lines=None):
        return self.client.post('/api/import/pdf/',{'file':__import__('io').BytesIO(tiny_pdf(lines or self.LINES))})

    def test_import_pdf_builds_persistent_queue(self):
        before=Template.objects.count()
        r=self.upload()
        self.assertEqual(r.status_code,200,r.content)
        self.assertEqual(r.json()['added'],4)
        self.assertEqual(r.json()['counts']['pending'],4)
        self.assertEqual(Template.objects.count(),before)  # queue, not templates
        rows=PendingImport.objects.filter(owner=self.user).order_by('order')
        self.assertEqual([x.name for x in rows],['','ASLIBTPVSTR','ASDCINSTRUCTIONSRALP','ASLIBPLAINTEXT'])
        self.assertIn('You may shower',rows[2].text)
        # Re-uploading the same PDF adds nothing.
        r2=self.upload()
        self.assertEqual((r2.json()['added'],r2.json()['skipped']),(0,4))
        self.assertEqual(PendingImport.objects.filter(owner=self.user).count(),4)
        self.assertEqual(self.client.get('/api/import/pdf/').status_code,405)

    def test_queue_list_skip_import_restore_clear(self):
        self.upload()
        listed=self.client.get('/api/imports/').json()
        self.assertEqual(len(listed['items']),4)
        tp=next(i for i in listed['items'] if i['name']=='ASLIBTPVSTR')
        # Skip one -> leaves the default queue, still counted as dismissed.
        self.client.post('/api/imports/%d/resolve/'%tp['id'],data=json.dumps({'action':'dismiss'}),content_type='application/json')
        self.assertEqual(len(self.client.get('/api/imports/').json()['items']),3)
        self.assertEqual(len(self.client.get('/api/imports/?dismissed=1').json()['items']),1)
        # Restore it.
        self.client.post('/api/imports/%d/resolve/'%tp['id'],data=json.dumps({'action':'restore'}),content_type='application/json')
        self.assertEqual(len(self.client.get('/api/imports/').json()['items']),4)
        # Mark another imported, linked to a real template.
        other=next(i for i in listed['items'] if i['name']=='ASLIBPLAINTEXT')
        self.client.post('/api/imports/%d/resolve/'%other['id'],data=json.dumps({'action':'imported','template_id':self.b['id']}),content_type='application/json')
        counts=self.client.get('/api/imports/').json()['counts']
        self.assertEqual((counts['pending'],counts['imported']),(3,1))
        self.assertEqual(self.client.get('/api/templates/').json()['pending_imports'],3)
        # Clearing resolved drops the imported row; skipped none remain.
        cleared=self.client.post('/api/imports/clear/',data=json.dumps({'scope':'resolved'}),content_type='application/json').json()
        self.assertEqual(cleared['deleted'],1)
        self.assertEqual(PendingImport.objects.filter(owner=self.user).count(),3)

    def test_resolve_all_skips_and_restores_in_bulk(self):
        self.upload()
        listed=self.client.get('/api/imports/').json()['items']
        self.assertEqual(len(listed),4)
        # One already imported must be left alone by a bulk skip.
        imp=listed[0]
        self.client.post('/api/imports/%d/resolve/'%imp['id'],data=json.dumps({'action':'imported','template_id':self.b['id']}),content_type='application/json')
        r=self.client.post('/api/imports/resolve-all/',data=json.dumps({'action':'dismiss'}),content_type='application/json').json()
        self.assertEqual(r['updated'],3)
        self.assertEqual((r['counts']['pending'],r['counts']['imported'],r['counts']['dismissed']),(0,1,3))
        self.assertEqual(len(self.client.get('/api/imports/').json()['items']),0)
        self.assertEqual(len(self.client.get('/api/imports/?dismissed=1').json()['items']),3)
        back=self.client.post('/api/imports/resolve-all/',data=json.dumps({'action':'restore'}),content_type='application/json').json()
        self.assertEqual(back['updated'],3)
        self.assertEqual((back['counts']['pending'],back['counts']['imported']),(3,1))
        self.assertEqual(self.client.post('/api/imports/resolve-all/',data=json.dumps({'action':'nope'}),content_type='application/json').status_code,400)

    def test_queue_is_owner_scoped(self):
        self.upload()
        self.client.force_login(get_user_model().objects.create_user('intruder'))
        self.assertEqual(self.client.get('/api/imports/').json()['items'],[])
        rid=PendingImport.objects.first().pk
        self.assertEqual(self.client.post('/api/imports/%d/resolve/'%rid,data=json.dumps({'action':'dismiss'}),content_type='application/json').status_code,404)

    def test_queue_save_is_atomic_and_cannot_be_repeated(self):
        self.upload()
        row=PendingImport.objects.filter(owner=self.user).first()
        data={'title':'Reviewed import','content':'<p>Reviewed source.</p>','pending_import_id':row.pk}
        before=Template.objects.count()
        def save(payload):
            return self.client.post('/api/templates/',data=json.dumps(payload),content_type='application/json')
        # Failed validation and failures after creation must release the claim.
        self.assertEqual(save(dict(data,title='')).status_code,400)
        with patch('library.views.record',side_effect=ValueError('Synthetic failure')):
            self.assertEqual(save(data).status_code,400)
        row.refresh_from_db()
        self.assertIsNone(row.imported_at)
        self.assertIsNone(row.imported_template_id)
        self.assertEqual(Template.objects.count(),before)
        response=save(data)
        self.assertEqual(response.status_code,201,response.content)
        row.refresh_from_db()
        self.assertEqual(row.imported_template_id,response.json()['id'])
        self.assertIsNotNone(row.imported_at)
        self.assertEqual(row.imported_template.revisions.count(),1)
        self.assertEqual(save(data).status_code,400)
        self.assertEqual(Template.objects.count(),before+1)

    def test_queue_save_rejects_other_owner_and_dismissed_entries(self):
        self.upload()
        row=PendingImport.objects.filter(owner=self.user).first()
        before=Template.objects.count()
        data={'title':'Import','content':'<p>Source.</p>','pending_import_id':row.pk}
        self.client.force_login(get_user_model().objects.create_user('intruder'))
        self.assertEqual(self.client.post('/api/templates/',data=json.dumps(data),content_type='application/json').status_code,400)
        self.client.force_login(self.user)
        row.dismissed=True;row.save()
        self.assertEqual(self.client.post('/api/templates/',data=json.dumps(data),content_type='application/json').status_code,400)
        self.assertEqual(Template.objects.count(),before)

    def test_queue_resolve_requires_owned_template(self):
        self.upload()
        row=PendingImport.objects.filter(owner=self.user).first()
        other=get_user_model().objects.create_user('other')
        foreign=Template.objects.create(owner=other,title='Other',content='<p>Other</p>')
        for tid,code in [(None,400),(foreign.pk,404)]:
            response=self.client.post('/api/imports/%d/resolve/'%row.pk,data=json.dumps({'action':'imported','template_id':tid}),content_type='application/json')
            self.assertEqual(response.status_code,code)
            row.refresh_from_db()
            self.assertIsNone(row.imported_at)

    def test_import_pdf_rejects_bad_input_and_anonymous(self):
        self.assertEqual(self.client.post('/api/import/pdf/',{}).status_code,400)
        r=self.client.post('/api/import/pdf/',{'file':__import__('io').BytesIO(b'this is not a pdf at all')})
        self.assertEqual(r.status_code,400)
        self.assertIn('PDF',r.json()['error'])
        self.assertEqual(PendingImport.objects.count(),0)
        guest=Client()
        self.assertEqual(guest.post('/api/import/pdf/',{}).status_code,401)
        self.assertEqual(guest.get('/api/imports/').status_code,401)


class CaseDrafts(TestCase):
    """Opt-in resumable case drafts: one per master template, 7-day expiry, export-excluded."""
    def setUp(self):
        cache.clear()
        self.user=get_user_model().objects.create_user('owner',password='synthetic-test-password')
        self.client.force_login(self.user)
        self.op=self.mk('Operative',kind='operative',content='<h2>Operative</h2><p>@AGE@ *** dissection.</p>')
        self.clinic=self.mk('Counseling',kind='clinic',content='<p>discussion</p>')
    def mk(self,title,**kw):
        r=self.client.post('/api/templates/',data=json.dumps({'title':title,'content':'<p>x</p>',**kw}),content_type='application/json')
        self.assertEqual(r.status_code,201,r.content)
        return r.json()
    def save(self,body):
        return self.client.post('/api/drafts/',data=json.dumps(body),content_type='application/json')

    def test_save_resume_overwrite_list_delete(self):
        r=self.save({'template_id':self.op['id'],'content':'<p>work in progress one</p>','label':'left off at nodes'})
        self.assertEqual(r.status_code,200,r.content)
        d=r.json()
        self.assertEqual(d['content'],'<p>work in progress one</p>')
        self.assertEqual((d['label'],d['base_version'],d['stale_base']),('left off at nodes',1,False))
        # one row per template — a repeat save overwrites in place
        r2=self.save({'template_id':self.op['id'],'content':'<p>work in progress two</p>'})
        self.assertEqual(CaseDraft.objects.filter(owner=self.user).count(),1)
        self.assertEqual(r2.json()['id'],d['id'])
        self.assertEqual(r2.json()['content'],'<p>work in progress two</p>')
        # surfaced on the template detail response, fetchable in full, listable, deletable
        self.assertEqual(self.client.get(f"/api/templates/{self.op['id']}/").json()['case_draft']['id'],d['id'])
        self.assertEqual(self.client.get(f"/api/drafts/{d['id']}/").json()['content'],'<p>work in progress two</p>')
        self.assertEqual(len(self.client.get('/api/drafts/').json()['items']),1)
        self.assertEqual(self.client.delete(f"/api/drafts/{d['id']}/").status_code,200)
        self.assertEqual(CaseDraft.objects.count(),0)
        self.assertIsNone(self.client.get(f"/api/templates/{self.op['id']}/").json()['case_draft'])

    def test_only_operative_and_procedure_kinds(self):
        self.assertEqual(self.save({'template_id':self.clinic['id'],'content':'<p>x</p>'}).status_code,400)
        self.assertEqual(self.save({'template_id':999999,'content':'<p>x</p>'}).status_code,404)
        self.assertEqual(CaseDraft.objects.count(),0)

    def test_content_sanitized_and_required(self):
        r=self.save({'template_id':self.op['id'],'content':'<p onclick="x()">hi</p><script>bad()</script>'})
        self.assertEqual(r.status_code,200,r.content)
        self.assertNotIn('script',r.json()['content'])
        self.assertNotIn('onclick',r.json()['content'])
        self.assertEqual(self.save({'template_id':self.op['id'],'content':'   '}).status_code,400)

    def test_stale_base_flag_when_master_advances(self):
        self.save({'template_id':self.op['id'],'content':'<p>draft</p>'})
        put=self.client.put(f"/api/templates/{self.op['id']}/",data=json.dumps(dict(self.op,content='<p>new master body</p>',version=1)),content_type='application/json')
        self.assertEqual(put.status_code,200,put.content)
        self.assertTrue(self.client.get(f"/api/templates/{self.op['id']}/").json()['case_draft']['stale_base'])

    def test_expired_drafts_are_pruned_on_access(self):
        self.save({'template_id':self.op['id'],'content':'<p>old</p>'})
        CaseDraft.objects.update(updated_at=timezone.now()-CaseDraft.TTL-timedelta(minutes=1))
        self.assertEqual(self.client.get('/api/drafts/').json()['items'],[])
        self.assertEqual(CaseDraft.objects.count(),0)

    def test_owner_scoped_and_auth_required(self):
        self.save({'template_id':self.op['id'],'content':'<p>mine</p>'})
        d=CaseDraft.objects.get()
        other=Client(); other.force_login(get_user_model().objects.create_user('other',password='pw'))
        self.assertEqual(other.get(f'/api/drafts/{d.pk}/').status_code,404)
        self.assertEqual(other.delete(f'/api/drafts/{d.pk}/').status_code,404)
        self.assertEqual(other.get('/api/drafts/').json()['items'],[])
        self.assertEqual(Client().get('/api/drafts/').status_code,401)

    def test_portable_export_excludes_case_drafts(self):
        self.save({'template_id':self.op['id'],'content':'<p>secret working draft text</p>'})
        self.assertNotIn('secret working draft text',self.client.get('/api/export/').content.decode())
