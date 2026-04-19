from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False, slow_mo=500)
    page = browser.new_page()
    
    print('1. 访问页面(禁用缓存)...')
    page.goto('http://localhost:18080', wait_until='networkidle')
    page.wait_for_timeout(2000)
    
    print('2. 检查按钮状态...')
    btn = page.locator('#createBtn')
    print(f'按钮可见: {btn.is_visible()}')
    print(f'按钮可用: {btn.is_enabled()}')
    print(f'按钮文本: {btn.text_content()}')
    
    print('3. 检查是否有多个按钮...')
    all_btns = page.locator('#createBtn').all()
    print(f'所有#createBtn数量: {len(all_btns)}')
    
    print('4. 点击前获取network请求...')
    with page.expect_request("**/api/agents**", timeout=10000) as req_info:
        page.click('#createBtn')
        req = req_info.value
        print(f'请求: {req.method} {req.url}')
        print(f'请求体: {req.post_body}')
    
    page.wait_for_timeout(5000)
    
    notice = page.locator('#notice').text_content()
    print(f'通知: {notice}')
    
    page.screenshot(path='/tmp/hermit-debug.png', full_page=True)
    browser.close()
