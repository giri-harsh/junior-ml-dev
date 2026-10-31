import { test, expect } from '@playwright/test';

/**
 * E2E tests for PRD S9.5: React run viewer
 * 
 * Requirements:
 * - API server must be running at http://localhost:8000
 * - Tests verify the UI can list runs and view run details
 * 
 * Note: Full upload→story flow requires backend integration not yet implemented.
 * These tests verify the existing viewer functionality.
 */

test.describe('Run Viewer', () => {
  test('should show login page when not authenticated', async ({ page }) => {
    await page.goto('/app/');
    
    // Should show login form
    await expect(page.locator('h2')).toHaveText('Sign in');
    await expect(page.locator('input[autocomplete="username"]')).toBeVisible();
    await expect(page.locator('input[type="password"]')).toBeVisible();
  });

  test('should handle login failure gracefully', async ({ page }) => {
    await page.goto('/app/');
    
    // Try to login with bad credentials
    await page.locator('input[autocomplete="username"]').fill('baduser');
    await page.locator('input[type="password"]').fill('badpass');
    await page.locator('button[type="submit"]').click();
    
    // Should show error
    await expect(page.locator('[role="alert"]')).toBeVisible();
  });

  test('should show runs list after successful login', async ({ page, context }) => {
    // Skip if no admin credentials configured
    const adminUser = process.env.ADMIN_USER;
    const adminPassword = process.env.ADMIN_PASSWORD;
    
    if (!adminUser || !adminPassword) {
      test.skip();
      return;
    }

    await page.goto('/app/');
    
    // Login
    await page.locator('input[autocomplete="username"]').fill(adminUser);
    await page.locator('input[type="password"]').fill(adminPassword);
    await page.locator('button[type="submit"]').click();
    
    // Should show runs list
    await expect(page.locator('h1')).toHaveText('Runs');
    await expect(page.locator('button:has-text("Refresh")')).toBeVisible();
    
    // Table should exist
    await expect(page.locator('table')).toBeVisible();
    await expect(page.locator('thead')).toContainText('Run');
    await expect(page.locator('thead')).toContainText('Status');
  });

  test('should navigate to run detail', async ({ page }) => {
    const adminUser = process.env.ADMIN_USER;
    const adminPassword = process.env.ADMIN_PASSWORD;
    
    if (!adminUser || !adminPassword) {
      test.skip();
      return;
    }

    await page.goto('/app/');
    
    // Login
    await page.locator('input[autocomplete="username"]').fill(adminUser);
    await page.locator('input[type="password"]').fill(adminPassword);
    await page.locator('button[type="submit"]').click();
    
    // Wait for runs list
    await expect(page.locator('h1')).toHaveText('Runs');
    
    // Check if there are any runs
    const rows = page.locator('tbody tr');
    const count = await rows.count();
    
    if (count === 0) {
      // No runs yet, verify empty state message
      await expect(page.locator('td')).toContainText('No runs yet');
      return;
    }
    
    // Click first run
    await page.locator('tbody tr:first-child button.link').click();
    
    // Should show run detail
    await expect(page.locator('button:has-text("← Runs")')).toBeVisible();
    await expect(page.locator('h2')).toBeVisible();
    await expect(page.locator('text=Status:')).toBeVisible();
  });

  test('should navigate back from run detail to runs list', async ({ page }) => {
    const adminUser = process.env.ADMIN_USER;
    const adminPassword = process.env.ADMIN_PASSWORD;
    
    if (!adminUser || !adminPassword) {
      test.skip();
      return;
    }

    await page.goto('/app/');
    
    // Login
    await page.locator('input[autocomplete="username"]').fill(adminUser);
    await page.locator('input[type="password"]').fill(adminPassword);
    await page.locator('button[type="submit"]').click();
    
    await expect(page.locator('h1')).toHaveText('Runs');
    
    // Check if there are any runs
    const rows = page.locator('tbody tr');
    const count = await rows.count();
    
    if (count > 0) {
      // Navigate to detail
      await page.locator('tbody tr:first-child button.link').click();
      await expect(page.locator('button:has-text("← Runs")')).toBeVisible();
      
      // Navigate back
      await page.locator('button:has-text("← Runs")').click();
      await expect(page.locator('h1')).toHaveText('Runs');
    }
  });
});

test.describe('API Health', () => {
  test('should have working healthz endpoint', async ({ request }) => {
    const response = await request.get('/healthz');
    expect(response.ok()).toBeTruthy();
    
    const body = await response.json();
    expect(body.status).toBe('ok');
  });

  test('should have working readyz endpoint', async ({ request }) => {
    const response = await request.get('/readyz');
    
    // May be 503 if database not ready, but should return JSON
    const body = await response.json();
    expect(body).toHaveProperty('status');
  });
});
