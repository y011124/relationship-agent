"""Reproducible isolated browser smoke test; synthetic data only."""
import os
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
import sys
import httpx
from playwright.sync_api import sync_playwright, expect

with tempfile.TemporaryDirectory() as d:
    env={**os.environ,'DATABASE_URL':'sqlite:///'+d+'/browser.sqlite','PERSONA_ENV':'development','PERSONA_MODE':'mock','PERSONA_ORIGIN':'http://127.0.0.1:8879','PERSONA_INVITE_CODE':''}
    process=subprocess.Popen([sys.executable,'persona_app.py','--port','8879'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                if httpx.get('http://127.0.0.1:8879/readyz').is_success:break
            except httpx.TransportError:pass
            time.sleep(.1)
        # Existing synthetic login avoids interacting with any external account or legal agreement.
        r=httpx.post('http://127.0.0.1:8879/api/auth/register',headers={'Origin':'http://127.0.0.1:8879'},json={'username':'qa_browser','password':'synthetic-password-123','adult':True,'consent':True})
        r.raise_for_status()
        with sync_playwright() as p:
            browser=p.chromium.launch()
            page=browser.new_page(viewport={'width':1360,'height':880})
            errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto('http://127.0.0.1:8879/')
            page.locator('#username').fill('qa_browser');page.locator('#password').fill('synthetic-password-123');page.locator('#auth-submit').click()
            expect(page.locator('#workspace')).to_be_visible()
            page.locator('#add-person').click();page.locator('#person-form [name=nickname]').fill('小林');page.locator('#person-form button[type=submit]').click()
            expect(page.locator('#person-title')).to_have_text('小林');page.locator('#talk-person').click()
            page.locator('#message-input').fill('小林昨天取消约会，我有点失望。');page.locator('#message-input').press('Enter')
            page.get_by_role('button',name='查看并确认',exact=True).click(timeout=10000);page.locator('#event-form button[type=submit]').click()
            expect(page.locator('.memory-card')).to_have_count(0)
            page.locator('#new-chat').click();page.locator('#message-input').fill('小林之前做过什么？');page.locator('#send').click()
            expect(page.locator('#messages')).to_contain_text('你之前确认记录过',timeout=10000)
            page.reload();expect(page.locator('#messages')).to_contain_text('你之前确认记录过')
            page.locator('#language').click();expect(page.locator('#new-chat')).to_contain_text('New chat')
            Path('outputs').mkdir(exist_ok=True);page.screenshot(path='outputs/persona-desktop.png',full_page=True)
            page.set_viewport_size({'width':390,'height':844});expect(page.locator('#menu-toggle')).to_be_visible()
            assert page.evaluate('document.documentElement.scrollWidth <= document.documentElement.clientWidth')
            page.screenshot(path='outputs/persona-mobile.png',full_page=True)
            assert not errors,errors
            browser.close()
            print('Browser flow passed: login, person, Enter, confirmation, cross-session recall, reload, language, mobile.')
    finally:
        process.terminate();process.wait(timeout=10)
