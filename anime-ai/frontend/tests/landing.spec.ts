import { test, expect } from '@playwright/test';

test.describe('Sakura AI Approved Landing Page & Public Routes', () => {
  test('renders approved hero, navbar, showcases, and footer with zero dead links or errors', async ({ page, isMobile }) => {
    const pageErrors: string[] = [];
    page.on('pageerror', (err) => pageErrors.push(err.message));

    await page.goto('/', { waitUntil: 'domcontentloaded' });

    // 1. Pitch-black theme & hero headline composition
    const hero = page.locator('section#hero');
    await expect(hero).toBeVisible();
    await expect(hero.locator('h1')).toContainText('Where imagination');
    await expect(hero.locator('h1')).toContainText('Blooms');

    // Approved hero art must load cleanly
    const heroImg = hero.locator('img[src*="sakura-hero"]');
    await expect(heroImg).toBeVisible();
    await expect
      .poll(async () => heroImg.evaluate((el: HTMLImageElement) => el.complete && el.naturalWidth > 0), {
        timeout: 15_000,
      })
      .toBe(true);

    // Approved hero MUST have zero CTA buttons inside #hero
    await expect(hero.locator('a, button')).toHaveCount(0);

    // 2. Navbar Sign-in & navigation (no Get Started button in navbar)
    const header = page.locator('header.landing-nav');
    await expect(header).toBeVisible();
    await expect(header.getByText('Get Started', { exact: false })).toHaveCount(0);

    if (isMobile) {
      await expect(header.locator('a[href="/login"]:visible').first()).toBeVisible();
      const menuBtn = header.locator('button[aria-controls="landing-mobile-menu"]');
      await expect(menuBtn).toBeVisible();
      await menuBtn.click();
      await expect(page.locator('#landing-mobile-menu')).toBeVisible();
      await expect(page.locator('#landing-mobile-menu a[href="/#sakura-code"]')).toBeVisible();
      await menuBtn.click();
    } else {
      await expect(header.locator('nav[aria-label="Main Navigation"] a[href="/#capabilities"]')).toBeVisible();
      await expect(header.locator('nav[aria-label="Main Navigation"] a[href="/#sakura-code"]')).toBeVisible();
      await expect(header.locator('nav[aria-label="Main Navigation"] a[href="/#images"]')).toBeVisible();
      await expect(header.locator('nav[aria-label="Main Navigation"] a[href="/#library"]')).toBeVisible();
      await expect(header.locator('a[href="/login"]').first()).toBeVisible();
    }

    // 3. Key showcases are rendered cleanly
    await expect(page.locator('#capabilities')).toBeVisible();
    await expect(page.locator('#sakura-code')).toBeVisible();
    await expect(page.locator('#images')).toBeVisible();
    await expect(page.locator('#library')).toBeVisible();
    await expect(page.locator('#how-it-works')).toBeVisible();

    // 4. Footer links & zero dead '#' hrefs anywhere on the page
    const footer = page.locator('footer.landing-footer');
    await expect(footer).toBeVisible();
    await expect(footer.locator('a[href="/privacy"]')).toBeVisible();
    await expect(footer.locator('a[href="/terms"]')).toBeVisible();
    await expect(footer.locator('a[href="/about"]')).toBeVisible();
    await expect(footer.locator('a[href="/contact"]')).toBeVisible();

    const deadHashLinks = await page.locator('a[href="#"]').count();
    expect(deadHashLinks).toBe(0);

    expect(pageErrors).toEqual([]);
  });

  test('Sign-in navigation works and never renders broken OAuth links', async ({ page }) => {
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await page.locator('header.landing-nav a[href="/login"]:visible').first().click();
    await expect(page).toHaveURL(/\/login$/);
    await expect(page.locator('h1')).toContainText('Welcome back');

    // Never render dead OAuth links when routes are not implemented
    await expect(page.locator('a[href*="/auth/oauth/google"]')).toHaveCount(0);
    await expect(page.locator('a[href*="/auth/oauth/github"]')).toHaveCount(0);
  });

  test('/privacy and /terms render cleanly with pre-launch legal review notice', async ({ page }) => {
    await page.goto('/privacy', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('h1')).toContainText('Privacy Policy');
    await expect(page.locator('main')).toContainText('Requires Legal Review');

    await page.goto('/terms', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('h1')).toContainText('Terms of Service');
    await expect(page.locator('main')).toContainText('Requires Legal Review');
  });
});
