"""Synthetic browser checks against a local server; creates and removes its own account."""
import os,sys,secrets
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django
django.setup()
# Playwright runs its own greenlet loop; this script's ORM calls are strictly sequential.
os.environ['DJANGO_ALLOW_ASYNC_UNSAFE']='true'
from django.contrib.auth import get_user_model
from playwright.sync_api import sync_playwright, expect
from library.models import Template,Revision
password=secrets.token_urlsafe(24)
user=get_user_model().objects.create_user('browser-'+secrets.token_hex(4),password=password)
try:
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='chrome',headless=True)
        context=browser.new_context(permissions=['clipboard-read','clipboard-write'])
        page=context.new_page(); page.set_default_timeout(10000); errors=[]
        page.on('response',lambda r: print(r.status,r.url,flush=True) if r.status>=400 else None)
        page.on('console',lambda m: print('Browser:',m.type,m.text,flush=True) if m.type=='error' else None)
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto('http://127.0.0.1:8765/')
        page.get_by_label('Username').fill(user.username)
        page.locator('#id_password').fill(password)
        page.get_by_role('button',name='Sign in',exact=True).click()
        page.get_by_role('button',name='+ New phrase / import').click()
        page.get_by_role('button',name='Load synthetic example').click()
        page.get_by_role('button',name='Use pasted source').click()
        page.get_by_role('button',name='Suggest split').click()
        assert '@MRN@' in page.locator('#header').inner_text()
        assert '@MRN@' not in page.locator('#content').inner_text()
        page.get_by_label('I reviewed reusable content').check()
        page.get_by_role('button',name='Approve import and save').click()
        page.get_by_role('button',name='Customize this case').wait_for()
        template=Template.objects.get(owner=user)
        baseline=template.content; revision_count=Revision.objects.filter(template=template).count()
        page.get_by_role('button',name='Customize this case').click()
        page.get_by_label('I reviewed this narrative').check()
        page.get_by_role('button',name='Copy plain text').click()
        expect(page.locator('#notice')).to_contain_text('Copied')
        copied=page.evaluate('navigator.clipboard.readText()')
        assert '@MRN@' not in copied and 'Indication for Procedure' in copied
        assert 'MOCK' not in copied
        page.get_by_label('Free-text instructions').fill('Significant periprostatic inflammation and scarring made dissection difficult.')
        page.get_by_role('button',name='Propose case revision').click()
        page.get_by_label('I reviewed the proposal').check()
        page.get_by_role('button',name='Accept reviewed text').click()
        assert 'scarring' in page.locator('#case-content').inner_text()
        page.get_by_label('I reviewed this narrative').check()
        page.get_by_role('button',name='Copy formatted').click()
        expect(page.locator('#notice')).to_contain_text('Copied')
        formats=page.evaluate('navigator.clipboard.read().then(xs=>xs[0].types)')
        assert 'text/html' in formats and 'text/plain' in formats
        assert page.evaluate('localStorage.length')==0 and page.evaluate('sessionStorage.length')==0
        template.refresh_from_db();assert template.content==baseline
        assert Revision.objects.filter(template=template).count()==revision_count
        page.screenshot(path='/private/tmp/smartphrase-case.png',full_page=True)
        page.once('dialog',lambda d:d.accept())
        page.get_by_role('button',name='Finish and clear').click()
        page.get_by_label('Search library').fill('SYNTHETIC_DEMO')
        page.get_by_role('button',name='Synthetic operative example').click()
        page.get_by_role('button',name='Edit master',exact=True).click()
        page.get_by_label('Title',exact=True).fill('Synthetic updated master')
        page.get_by_label('I reviewed reusable content').check()
        page.get_by_role('button',name='Save new master revision').click()
        page.get_by_role('button',name='Edit master',exact=True).wait_for()
        template.refresh_from_db();assert template.version==2
        page.get_by_label('Select Synthetic updated master').check()
        page.get_by_role('button',name='Update selected masters').click()
        page.get_by_label('Describe your practice change').fill('Significant periprostatic inflammation and scarring made dissection difficult.')
        page.get_by_role('button',name='Propose selected updates').click()
        page.get_by_label('I reviewed the proposal').check()
        page.get_by_role('button',name='Accept reviewed text').click()
        expect(page.locator('#notice')).to_contain_text('revision 3')
        template.refresh_from_db();assert template.version==3
        page.once('dialog',lambda d:d.accept())
        page.get_by_role('button',name='Library',exact=True).click()
        page.get_by_role('button',name='Synthetic updated master').click()
        page.screenshot(path='/private/tmp/smartphrase-library.png',full_page=True)
        page.set_viewport_size({'width':390,'height':844})
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        page.get_by_role('button',name='Settings',exact=True).click()
        page.get_by_role('heading',name='Settings & portability').wait_for()
        assert not errors,errors
        browser.close()
        print('PASS: login, import, split, search, manual revision, temporary case, AI review, plain/formatted clipboard, clear, selected approval, settings, mobile width, no browser storage or JS errors.')
finally:
    user.delete()
