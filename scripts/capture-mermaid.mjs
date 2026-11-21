import { chromium } from 'playwright';

async function capture() {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
  });
  const page = await context.newPage();

  console.log('Navigating to chat session...');
  await page.goto('http://localhost:5173/chat/sess_4bc47e767d3748bfabbf', { waitUntil: 'networkidle' });
  await page.waitForTimeout(1500);

  // Check if canvas is already open, if not, click on the artifact card
  const artifactCard = page.locator('text=eda-microservices-architecture').first();
  if (await artifactCard.isVisible()) {
    console.log('Clicking artifact card...');
    await artifactCard.click();
    await page.waitForTimeout(2000);
  }

  // Wait for mermaid SVG
  console.log('Waiting for mermaid svg...');
  await page.waitForSelector('.mermaid-stage svg', { timeout: 10000 });
  await page.waitForTimeout(1000);

  // Click zoom in button a few times to get a close-up
  const zoomInBtn = page.locator('button[title="확대"]');
  if (await zoomInBtn.isVisible()) {
    for (let i = 0; i < 4; i++) {
      await zoomInBtn.click();
      await page.waitForTimeout(150);
    }
  }
  await page.waitForTimeout(500);

  // Take screenshot of the full page / canvas
  await page.screenshot({ path: '/tmp/screenshot_mermaid_zoomed.png' });
  console.log('Zoomed screenshot saved to /tmp/screenshot_mermaid_zoomed.png');

  // Toggle dark mode via actual sidebar button so React state updates
  console.log('Toggling dark theme via UI button...');
  const themeButton = page.locator('button:has-text("Dark theme")');
  if (await themeButton.isVisible()) {
    await themeButton.click();
    await page.waitForTimeout(2000);
  }
  await page.screenshot({ path: '/tmp/screenshot_mermaid_dark.png' });
  console.log('Dark screenshot saved to /tmp/screenshot_mermaid_dark.png');

  await browser.close();
}

capture().catch((err) => {
  console.error('Capture failed:', err);
  process.exit(1);
});
