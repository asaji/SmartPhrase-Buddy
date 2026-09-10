"""Browser regressions for draft integrity, with synthetic data and no external AI."""
from browser_support import synthetic_server
from playwright.sync_api import sync_playwright, expect

with synthetic_server() as base_url:
    from django.contrib.auth import get_user_model
    from library.models import Template, Revision, PendingImport, CaseDraft, SharedChoice
    from library.services import snapshot
    user=get_user_model().objects.create_user('regression',password='synthetic-test-password')
    def template(title,kind,content):
        t=Template.objects.create(owner=user,title=title,kind=kind,content=content)
        Revision.objects.create(template=t,version=1,snapshot=snapshot(t))
        return t
    procedure=template('Procedure regression','procedure','<p>[[Bladder: normal | mass]]</p><p>[[EBL: minimal | moderate]]</p><p>Keep <strong>this formatting</strong>.</p>')
    operative=template('Checklist regression','operative','<p>Age @AGE@.</p><p>Drain ***.</p>')
    extent=template('Operative choice regression','operative','<p>[[Extent: RALP without pelvic lymphadenectomy | RALP with standard pelvic lymphadenectomy | RALP with extended pelvic lymphadenectomy]]</p><p>Drain ***.</p>')
    removal=template('Removal regression','operative','<p>Keep <strong>this sentence</strong>. Device *** at *** location. Keep <em>this too</em>.</p>')
    reuse=template('Choice reuse regression','operative','<p>Planned approach: [[Approach: open | robotic | laparoscopic]].</p><p>The [[Approach]] technique was used throughout.</p><p>Specimen removed via the [[Approach]] port site.</p><p>Closure per [[Closure]] preference.</p>')
    formatted=template('Formatted regression','procedure','<p>Value <strong>**</strong>*.</p><p>[[Field: <strong>one</strong> | two]]</p><ul><li>Parent <strong>**</strong>*<ul><li>Child @TOKEN@</li></ul></li></ul>')
    shared_asst=template('Shared assistant regression','operative','<p>Assisted by [[@Assistant]].</p><p>Closure performed with [[@Assistant]] at the bedside.</p><p>Drain ***.</p>')
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='chrome',headless=True)
        page=browser.new_page();page.set_default_timeout(10000)
        errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
        accept_dialogs=[True]
        page.on('dialog',lambda dialog:dialog.accept() if accept_dialogs[0] else dialog.dismiss())
        page.goto(base_url+'/')
        page.get_by_label('Username').fill(user.username)
        page.locator('#id_password').fill('synthetic-test-password')
        page.get_by_role('button',name='Sign in',exact=True).click()
        def open_template(t,master=False):
            page.locator('#library-nav').click()
            page.locator(f'[data-open="{t.pk}"]').click()
            page.locator('#edit' if master else '#case').click()
            selector='#content' if master else '#p-content' if t.kind=='procedure' else '#case-content'
            expect(page.locator(selector+' .tiptap')).to_be_visible()
            # The status request finishes wiring controls after mounting the editor.
            if not master:
                expect(page.locator('#draft-history-body .hist')).to_have_count(1)
            return page.locator(selector+' .tiptap')
        def check_field(index,value,checked=True):
            page.locator(f'input[data-m="{index}"][value="{value}"]').set_checked(checked)
        def check_case_field(index,value,checked=True):
            page.locator(f'input[data-cm="{index}"][value="{value}"]').set_checked(checked)

        editor=open_template(procedure)
        check_field(0,'normal');page.locator('#p-generate').click()
        expect(editor).to_contain_text('Bladder: normal.')
        expect(editor).to_contain_text('[[EBL:')
        check_field(1,'minimal');page.locator('#p-generate').click()
        expect(editor).to_contain_text('EBL: minimal.')
        expect(editor).not_to_contain_text('EBL: normal.')
        check_field(0,'normal',False);check_field(0,'mass');page.locator('#p-generate').click()
        expect(editor).to_contain_text('Bladder: mass.')
        expect(editor.locator('strong')).to_have_text('this formatting')
        editor.fill('Manual note to preserve.')
        accept_dialogs[0]=False;page.locator('#p-generate').click()
        expect(editor).to_have_text('Manual note to preserve.')
        accept_dialogs[0]=True;page.locator('#p-generate').click()
        expect(editor).to_contain_text('EBL: minimal.')
        page.locator('#draft-history summary').click()
        expect(page.locator('#draft-history-body')).to_contain_text('Before filling fields')
        # Clearing all selections restores the original fields, not old values.
        check_field(0,'mass',False);check_field(1,'minimal',False);page.locator('#p-generate').click()
        expect(editor).to_contain_text('[[Bladder:')
        expect(editor).to_contain_text('[[EBL:')
        print('PASS: repeated/changed procedure selections and manual-edit protection')

        editor=open_template(extent)
        expect(page.locator('#case-fields')).to_contain_text('Extent')
        check_case_field(0,'RALP with standard pelvic lymphadenectomy')
        page.locator('#case-generate').click()
        expect(editor).to_contain_text('Extent: RALP with standard pelvic lymphadenectomy.')
        expect(editor).to_contain_text('Drain ***.')  # the marker never touches unrelated *** tokens
        # The AI checklist still surfaces the untouched *** independently of the picked option.
        page.locator('#checklist').click()
        page.locator('[data-fill="0"]').fill('foley catheter');page.locator('[data-literal="0"]').check()
        page.locator('#apply-checklist').click()
        expect(editor).to_contain_text('Drain foley catheter.')
        expect(editor).to_contain_text('Extent: RALP with standard pelvic lymphadenectomy.')
        # Switching the pick before regenerating replaces the earlier choice, not the checklist answer.
        check_case_field(0,'RALP with standard pelvic lymphadenectomy',False);check_case_field(0,'RALP with extended pelvic lymphadenectomy')
        page.locator('#case-generate').click()
        expect(editor).to_contain_text('Extent: RALP with extended pelvic lymphadenectomy.')
        expect(editor).not_to_contain_text('standard pelvic lymphadenectomy')
        editor=open_template(extent)
        page.locator('#strip-tokens').click()
        expect(editor).not_to_contain_text('[[')
        expect(editor).not_to_contain_text('***')
        print('PASS: operative [[ … ]] choice fields fill, coexist with the AI checklist, and strip cleanly')

        # A variable declared once ([[Approach: … ]]) and referenced by name ([[Approach]]) elsewhere
        # is one control that fills every occurrence; a name only ever used bare is free-text + warning.
        editor=open_template(reuse)
        expect(page.locator('#case-fields .pfield')).to_have_count(2)
        expect(page.locator('#case-fields')).to_contain_text('Approach')
        expect(page.locator('#case-fields')).to_contain_text('3×')  # three occurrences share one control
        expect(page.locator('input[data-cm="0"]')).to_have_count(3)  # the declared option list
        expect(page.locator('input[data-cm="1"]')).to_have_count(0)  # Closure: undeclared, free text only
        expect(page.locator('#case-fields .pfield').nth(1)).to_contain_text('No options declared')
        check_case_field(0,'robotic');page.locator('#case-generate').click()
        expect(editor).to_contain_text('Planned approach: robotic.')
        expect(editor).to_contain_text('The robotic technique was used throughout.')
        expect(editor).to_contain_text('Specimen removed via the robotic port site.')
        expect(editor).not_to_contain_text('[[Approach')
        expect(editor).to_contain_text('[[Closure]]')  # left untouched until its free text is given
        page.locator('input[data-cmfree="1"]').fill('running barbed suture')
        page.locator('#case-generate').click()
        expect(editor).to_contain_text('Closure per running barbed suture preference.')
        expect(editor).not_to_contain_text('[[Closure')
        # Switching the shared pick re-fills every occurrence from the original template.
        check_case_field(0,'robotic',False);check_case_field(0,'open')
        page.locator('#case-generate').click()
        expect(editor).to_contain_text('Planned approach: open.')
        expect(editor).to_contain_text('Specimen removed via the open port site.')
        expect(editor).not_to_contain_text('robotic')
        editor=open_template(reuse,master=True)
        expect(page.locator('#fixed-warning')).to_contain_text('Closure')
        expect(page.locator('#fixed-warning')).to_contain_text('never declared with options')
        expect(page.locator('#fixed-warning')).not_to_contain_text('“Approach”')
        print('PASS: declare-once choice variables fill every reference from one control; undeclared ones warn')

        editor=open_template(operative)
        page.locator('#checklist').click()
        page.locator('[data-fill="0"]').fill('50');page.locator('[data-literal="0"]').check()
        page.locator('#apply-checklist').click()
        expect(editor).to_contain_text('Age 50.')
        expect(editor).to_contain_text('Drain ***.')
        expect(page.locator('#apply-checklist')).to_have_count(0)
        page.locator('#checklist').click()
        expect(page.locator('[data-fill]')).to_have_count(1)
        page.locator('[data-fill="0"]').fill('catheter');page.locator('[data-literal="0"]').check()
        editor.fill('Manual *** changed.')
        page.locator('#apply-checklist').click()
        expect(page.locator('#notice')).to_contain_text('Rebuild the checklist')
        expect(editor).to_have_text('Manual *** changed.')
        print('PASS: consumed and stale checklists cannot move answers')

        delayed_checklist=[]
        page.route('**/api/finalize/',lambda route:delayed_checklist.append(route))
        editor=open_template(operative);page.locator('#checklist').click()
        editor.fill('New draft *** while checklist was loading.')
        assert delayed_checklist
        delayed_checklist.pop().fulfill(json={'provider':'mock','items':[]})
        expect(page.locator('#notice')).to_contain_text('changed while building')
        expect(editor).to_have_text('New draft *** while checklist was loading.')
        page.unroute('**/api/finalize/')

        for remove_index,fill_index in [(0,1),(1,0)]:
            editor=open_template(removal)
            page.locator('#checklist').click()
            page.locator(f'[data-mode="{remove_index}"]').select_option('remove')
            page.locator(f'[data-fill="{fill_index}"]').fill('left')
            page.locator(f'[data-literal="{fill_index}"]').check()
            page.locator('#apply-checklist').click()
            expect(editor).not_to_contain_text('Device')
            expect(editor).not_to_contain_text('left')
            expect(editor.locator('strong')).to_have_text('this sentence')
            expect(editor.locator('em')).to_have_text('this too')
        editor=open_template(formatted)
        page.locator('#p-strip').click()
        expect(editor).not_to_contain_text('***')
        expect(editor).not_to_contain_text('[[')
        expect(editor).not_to_contain_text('@TOKEN@')
        expect(page.locator('#p-strip')).to_be_disabled()
        print('PASS: overlapping removal/fills and formatted/nested placeholder stripping')

        # Synthetic grammar response, independently delayed to simulate typing
        # both while a request runs and after its review card is displayed.
        pending=[]
        page.route('**/api/grammar/',lambda route:pending.append(route))
        def finish_grammar():
            page.wait_for_function('true')  # dispatch pending route callbacks
            assert pending,'Grammar request was not sent'
            route=pending.pop(0)
            source=route.request.post_data_json['content']
            route.fulfill(json={'provider':'synthetic','proposal':{'source':source,'content':source+'<p>Grammar correction.</p>','summary':'Synthetic correction','questions':[],'warnings':[]}})
        for t,master in [(operative,False),(procedure,False),(operative,True)]:
            for during_request in [False,True]:
                editor=open_template(t,master)
                if master:
                    page.locator('#confirm-master').check()
                    page.locator('#save').click()
                else:
                    page.locator('#case-grammar' if t.kind=='operative' else '#p-grammar').click()
                if during_request:
                    editor.fill('New manual text during grammar request.')
                    finish_grammar()
                else:
                    finish_grammar()
                    expect(page.locator('.review')).to_have_count(1)
                    editor.fill('New manual text after grammar request.')
                    page.locator('.review .ack').check();page.locator('.review .accept').click()
                expect(page.locator('#notice')).to_contain_text('narrative changed')
                expect(editor).to_contain_text('New manual text')
                expect(editor).not_to_contain_text('Grammar correction')
                t.refresh_from_db();assert t.version==1
        # A response from a closed case must not appear in the next case.
        editor=open_template(operative);page.locator('#case-grammar').click()
        editor=open_template(procedure);finish_grammar()
        expect(page.locator('.review')).to_have_count(0)
        expect(editor).to_contain_text('[[Bladder:')
        print('PASS: stale grammar results blocked in all editors and after navigation')

        # A current proposal must still work, including an atomic master save.
        for t,master in [(operative,False),(procedure,False),(operative,True)]:
            editor=open_template(t,master)
            if master:
                page.locator('#confirm-master').check();page.locator('#save').click()
            else:
                page.locator('#case-grammar' if t.kind=='operative' else '#p-grammar').click()
            finish_grammar()
            page.locator('.review .ack').check();page.locator('.review .accept').click()
            if master:
                expect(page.locator('#notice')).to_contain_text('Master saved as revision 2')
                t.refresh_from_db();assert t.version==2
            else:
                expect(editor).to_contain_text('Grammar correction.')
        page.unroute('**/api/grammar/')

        row=PendingImport.objects.create(owner=user,batch='synthetic',name='Queued regression',text='Queued source.',html='<p>Queued source.</p>',text_hash='synthetic')
        before=Template.objects.filter(owner=user).count()
        page.locator('#imports-nav').click()
        page.locator(f'.qopen[data-open="{row.pk}"]').click()
        page.locator('#confirm-master').check();page.locator('#save').click()
        expect(page.locator('#notice')).to_contain_text('Removed from the import queue')
        row.refresh_from_db()
        assert row.imported_at and row.imported_template_id
        assert row.imported_template.revisions.count()==1
        assert Template.objects.filter(owner=user).count()==before+1
        expect(page.locator('.qopen')).to_have_count(0)
        print('PASS: current grammar proposals and atomic queued import through the UI')

        # "Skip all" dismisses every pending row at once; "Restore all" brings them back.
        for i in range(3):
            PendingImport.objects.create(owner=user,batch='bulk',name=f'Bulk {i}',text=f'Bulk source {i}.',html=f'<p>Bulk source {i}.</p>',text_hash=f'bulk-{i}',order=i)
        page.locator('#imports-nav').click()
        expect(page.locator('.qopen')).to_have_count(3)
        page.locator('#skip-all').click()  # confirm() auto-accepted
        expect(page.locator('#notice')).to_contain_text('Skipped 3 phrases')
        expect(page.locator('.qopen')).to_have_count(0)
        assert PendingImport.objects.filter(owner=user,batch='bulk',dismissed=True).count()==3
        page.locator('#toggle-skipped').click()
        expect(page.locator('.qopen')).to_have_count(3)
        page.locator('#skip-all').click()  # now labelled "Restore all"
        expect(page.locator('#notice')).to_contain_text('Restored 3 phrases')
        assert PendingImport.objects.filter(owner=user,batch='bulk',dismissed=False,imported_at__isnull=True).count()==3
        expect(page.locator('.qopen')).to_have_count(3)
        print('PASS: import queue Skip all / Restore all bulk actions')

        # Master editor "ask AI to improve this note" — proposes a reviewed diff into the editor
        # only; nothing is persisted until the surgeon confirms and saves a new revision.
        editor=open_template(operative,master=True)
        page.locator('#improve summary').click()
        page.get_by_label('Instructions',exact=True).fill('Significant periprostatic inflammation and scarring made dissection difficult.')
        page.get_by_role('button',name='Propose improvement').click()
        expect(page.locator('.review')).to_have_count(1)
        page.locator('.review .ack').check();page.locator('.review .accept').click()
        expect(editor).to_contain_text('scarring')
        operative.refresh_from_db();assert operative.version==2  # accepted into the editor only, not yet saved
        page.locator('#confirm-master').check();page.locator('#save').click()
        expect(page.locator('#notice')).to_contain_text('revision 3')
        operative.refresh_from_db();assert operative.version==3 and 'scarring' in operative.content
        print('PASS: master editor AI-improve stages a reviewed diff into the editor; save persists it')

        # Master editor "Reflow wrapped lines" — merges <p> fragments split at Epic's PDF
        # hard word-wrap back into flowing paragraphs; label lines and blank-line breaks stay.
        reflow=template('Reflow regression','operative',
            '<p><strong>Surgeon</strong>: A B, MD</p>'
            '<p>The dissection was carried down to the fascia which was then incised sharply along the length of the</p>'
            '<p>incision. The muscle was split and the peritoneum was swept medially.</p>'
            '<p></p>'
            '<p><strong>Anesthesia</strong>: General</p>')
        editor=open_template(reflow,master=True)
        html_before=page.evaluate("document.querySelector('#content .tiptap').innerHTML")
        assert html_before.count('<p>')>=4,html_before
        page.locator('#reflow').click()  # confirm() auto-accepted
        html_after=page.evaluate("document.querySelector('#content .tiptap').innerHTML")
        assert 'along the length of the incision. The muscle was split' in html_after,html_after
        assert html_after.count('<p>')<html_before.count('<p>'),html_after  # prose fragments merged
        assert 'Surgeon</strong>: A B, MD</p>' in html_after,html_after     # label line untouched
        assert 'Anesthesia</strong>: General</p>' in html_after,html_after
        reflow.refresh_from_db();assert reflow.version==1  # editor only, not saved
        print('PASS: master editor reflow merges Epic hard-wrapped paragraphs, keeps label lines')

        # Opt-in "Save to my account" — one resumable server copy per template.
        # Resume from the library preview restores the exact working narrative in a
        # freshly mounted editor (the cross-device path); Finish and clear can delete it.
        operative.refresh_from_db()
        editor=open_template(operative)
        editor.fill('Case in progress: nodes done, closing next. @AGE@ ***.')
        page.locator('#case-save-label').fill('left off at closure')
        page.locator('#case-save-account').click()
        expect(page.locator('#notice')).to_contain_text('Saved to your account')
        draft=CaseDraft.objects.get(owner=user,template=operative)
        assert (draft.kind,draft.base_version,draft.label)==('operative',operative.version,'left off at closure'),draft.__dict__
        assert 'nodes done, closing next' in draft.content,draft.content
        editor.fill('Case in progress: everything done, ready to copy.')
        page.locator('#case-save-account').click()
        expect(page.locator('#notice')).to_contain_text('Saved to your account')
        assert CaseDraft.objects.filter(owner=user,template=operative).count()==1  # overwritten in place
        page.locator('#library-nav').click()
        page.locator(f'[data-open="{operative.pk}"]').click()
        expect(page.locator('#case-resume')).to_be_visible()
        page.locator('#case-resume').click()
        resumed=page.locator('#case-content .tiptap')
        expect(resumed).to_be_visible()
        expect(resumed).to_contain_text('everything done, ready to copy')
        expect(page.locator('.intro')).to_contain_text('Resumed from the copy you saved')
        page.locator('#finish').click()  # confirm() + "also delete" both auto-accepted
        expect(page.locator('#library-nav')).to_be_visible()
        assert CaseDraft.objects.filter(owner=user,template=operative).count()==0
        print('PASS: save case draft to account, resume from library preview, delete on finish')

        # Shared choice variable: define the option list once in Settings, reference it
        # in any template as [[@Assistant]]; the case editor fills every occurrence from
        # one control, and editing the roster needs no template edit.
        page.locator('#settings-nav').click()
        page.locator('#new-choice-label').fill('Assistant')
        page.locator('#new-choice-options').fill('James\nDavid\nTeresa')
        page.locator('#add-choice').click()
        expect(page.locator('#choice-list')).to_contain_text('Assistant')
        assert SharedChoice.objects.filter(owner=user,label='Assistant').count()==1
        editor=open_template(shared_asst)
        expect(page.locator('#case-fields .pfield')).to_have_count(1)          # both [[@Assistant]] share one control
        expect(page.locator('#case-fields')).to_contain_text('2×')
        expect(page.locator('#case-fields')).to_contain_text('Shared list')
        expect(page.locator('input[data-cm="0"]')).to_have_count(3)            # options from the shared list
        check_case_field(0,'David');page.locator('#case-generate').click()
        expect(editor).to_contain_text('Assisted by David.')
        expect(editor).to_contain_text('with David at the bedside')
        # Grow the roster in Settings; the template follows with no edit of its own.
        page.locator('#settings-nav').click()
        box=page.locator('#choice-list [data-choice]').first
        box.locator('[data-copts]').fill('James\nDavid\nTeresa\nRavi')
        box.locator('[data-save-choice]').click()
        expect(page.locator('#notice')).to_contain_text('Saved')
        editor=open_template(shared_asst)
        expect(page.locator('input[data-cm="0"][value="Ravi"]')).to_have_count(1)
        # Master editor: a resolved [[@Assistant]] does not warn; an unknown [[@X]] does.
        editor=open_template(shared_asst,master=True)
        expect(page.locator('#shared-ref')).to_contain_text('@Assistant')
        expect(page.locator('#fixed-warning')).not_to_contain_text('Assistant')
        editor.fill('Assisted by [[@Nonexistent]].')
        expect(page.locator('#fixed-warning')).to_contain_text('does not exist')
        shared_asst.refresh_from_db();assert shared_asst.version==1
        print('PASS: shared choice variable resolves [[@Label]] from Settings across templates')

        assert not errors,errors
        assert page.evaluate('localStorage.length + sessionStorage.length')==0
        browser.close()
    print('PASS: all browser regressions; synthetic database discarded')
