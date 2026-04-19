import { chromium } from 'playwright';

const browser = await chromium.launch({ headless: false });
const page = await browser.newPage();

console.log('1. 访问页面...');
await page.goto('http://localhost:18080');
await page.waitForTimeout(2000);

console.log('2. 检查下拉框...');
const options = await page.locator('#agentType option').allTextContents();
console.log('选项:', options);

console.log('3. 输入名称并点击创建...');
await page.fill('#agentName', 'playwright-test');
await page.click('#createBtn');
await page.waitForTimeout(3000);

const notice = await page.locator('#notice').textContent();
console.log('结果:', notice);

await page.screenshot({ path: '/tmp/hermit-result.png', fullPage: true });
console.log('截图: /tmp/hermit-result.png');

await browser.close();
console.log('完成!');
