from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False, slow_mo=500)
    page = browser.new_page()
    
    page.on("console", lambda msg: print(f"浏览器日志: {msg.text}"))
    page.on("request", lambda req: print(f"请求: {req.method} {req.url}"))
    page.on("response", lambda res: print(f"响应: {res.status} {res.url}"))
    
    print('1. 访问页面...')
    page.goto('http://localhost:18080')
    page.wait_for_timeout(3000)
    
    print('2. 检查下拉框...')
    options = page.locator('#agentType option').all_text_contents()
    print('选项:', options)
    
    print('3. 点击创建按钮...')
    page.click('#createBtn')
    page.wait_for_timeout(8000)
    
    notice = page.locator('#notice').text_content()
    print('通知内容:', repr(notice))
    
    print('4. 检查docker容器...')
    page.screenshot(path='/tmp/hermit-full.png', full_page=True)
    print('截图: /tmp/hermit-full.png')
    
    browser.close()
