from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()
    
    print('1. 访问页面...')
    page.goto('http://localhost:18080')
    page.wait_for_timeout(2000)
    
    print('2. 检查下拉框...')
    options = page.locator('#agentType option').all_text_contents()
    print('选项:', options)
    
    print('3. 输入名称并点击创建...')
    page.fill('#agentName', 'pw-final-test')
    page.click('#createBtn')
    page.wait_for_timeout(5000)
    
    notice = page.locator('#notice').text_content()
    print('结果:', notice)
    
    page.screenshot(path='/tmp/hermit-final.png', full_page=True)
    print('截图保存到: /tmp/hermit-final.png')
    
    browser.close()
    print('测试完成!')
