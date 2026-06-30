import { test, expect } from '@playwright/test';

test('Navigate to LLM Extraction page and check for console errors', async ({ page }) => {
  // Collect all console messages
  const consoleErrors: string[] = [];
  const consoleWarnings: string[] = [];
  const consoleLogs: string[] = [];

  page.on('console', (msg) => {
    const text = msg.text();
    const type = msg.type();
    if (type === 'error') {
      consoleErrors.push(`[${type}] ${text}`);
    } else if (type === 'warning') {
      consoleWarnings.push(`[${type}] ${text}`);
    } else {
      consoleLogs.push(`[${type}] ${text}`);
    }
  });

  // Also capture uncaught page errors
  page.on('pageerror', (err) => {
    consoleErrors.push(`[PAGE_ERROR] ${err.message}`);
  });

  // 1. Navigate to the app
  await page.goto('http://localhost:5173/', { waitUntil: 'networkidle' });
  consoleLogs.push('--- Initial page loaded ---');

  // Wait for app to render
  await page.waitForSelector('.sidebar', { timeout: 10000 });

  // 2. Click on the "LLM 提取" navigation link in the sidebar
  const llmNavLink = page.locator('a[href="#/llm-extraction"]');
  await expect(llmNavLink).toBeVisible({ timeout: 10000 });
  await llmNavLink.click();

  // 3. Wait 3 seconds for the page to load and render
  await page.waitForTimeout(3000);

  // 4. Take a screenshot
  await page.screenshot({
    path: 'e2e/screenshots/llm-extraction-page.png',
    fullPage: true,
  });

  // 5. Report findings
  console.log('=== CONSOLE LOGS ===');
  consoleLogs.forEach((log) => console.log(log));

  console.log('\n=== CONSOLE WARNINGS ===');
  consoleWarnings.forEach((warn) => console.log(warn));

  console.log('\n=== CONSOLE ERRORS ===');
  consoleErrors.forEach((err) => console.log(err));

  // 6. Determine if the page rendered content after navigation
  const mainContent = page.locator('main');
  const mainHTML = await mainContent.innerHTML();
  const hasContent = mainHTML.length > 50; // more than just empty wrapper
  const bodyText = await page.locator('body').innerText();

  console.log('\n=== PAGE STATE ===');
  console.log(`Has sidebar: ${await page.locator('.sidebar').isVisible()}`);
  console.log(`Main content length: ${mainHTML.length} chars`);
  console.log(`Has meaningful content: ${hasContent}`);
  console.log(`Body text sample (first 500 chars): ${bodyText.substring(0, 500)}`);

  // Save the body text to a file for later inspection
  await page.evaluate((html) => {
    const el = document.createElement('div');
    el.id = 'e2e-debug-body';
    el.style.display = 'none';
    el.textContent = html;
    document.body.appendChild(el);
  }, bodyText);

  // Assertions
  expect(hasContent).toBe(true);
  expect(consoleErrors.length).toBe(0);
});
