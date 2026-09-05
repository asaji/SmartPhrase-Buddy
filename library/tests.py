import json
from unittest.mock import patch
from django.test import TestCase, Client, override_settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from .models import Template, Revision
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
