from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False, slow_mo=500)
    page = browser.new_page()
    
    errors = []
    page.on("console", lambda msg: errors.append(f"[{msg.type}] {msg.text}"))
    page.on("pageerror", lambda err: errors.append(f"[PAGE ERROR] {err}"))
    
    print('1. 访问页面...')
    page.goto('http://localhost:18080', wait_until='networkidle')
    page.wait_for_timeout(2000)
    
    print('2. 检查错误...')
    for e in errors:
        print(e)
    
    print('3. 尝试点击...')
    page.click('#createBtn')
    page.wait_for_timeout(3000)
    
    print('4. 点击后的错误...')
    for e in errors:
        print(e)
    
    page.screenshot(path='/tmp/hermit-console.png', full_page=True)
    browser.close()
