import { expect, test } from '@playwright/test';

// One pass through the view as a reader makes it: search, a work, a result, and the graph of what it rests on. The corpus is demos/synthetic, so every string here is a fact about that fixture.
const API = 'http://127.0.0.1:8793';
const TOP = 'arxiv:2401.00002v1#thm-1.1';

test('a reader searches, opens a work, and reads a result with its dependencies', async ({ page }) => {
	await page.goto(`/?q=valuated+matroids&api=${encodeURIComponent(API)}`);
	await expect(page.getByText('Tropical cycles on fans of valuated matroids')).toBeVisible();
	await expect(page.getByText(/3 works · 4 versions · 7 results/)).toBeVisible();

	await page.getByRole('link', { name: 'Tropical cycles on fans of valuated matroids' }).click();
	await expect(page.getByRole('heading', { name: /Tropical cycles/ })).toBeVisible();
	await expect(page.getByRole('heading', { name: /arxiv:2401\.00001v1/ })).toBeVisible();
	await expect(page.getByRole('heading', { name: /arxiv:2401\.00001v2/ })).toBeVisible();
	// what it cites is named as a work, never as one of its own versions
	await expect(page.locator('ul.cites').getByRole('link', { name: 'arxiv:2401.00002', exact: true })).toBeVisible();

	await page.goto(`/result?key=${encodeURIComponent(TOP)}`);
	await expect(page.getByRole('heading', { name: /Theorem 1\.1/ })).toBeVisible();
	await expect(page.locator('.panel').first()).toContainText('Let');
	await expect(page.getByRole('heading', { name: 'Proof as the paper gives it' })).toBeVisible();

	// a citation inside the proof is a link where the linker resolved it, and plain where it did not
	await expect(page.locator('.proof a.cite', { hasText: 'Theorem 1.1' })).toHaveAttribute('href', /arxiv%3A2401\.00001v2%23thm-1\.1/);
	await expect(page.locator('.proof a.cite', { hasText: 'third' })).toHaveAttribute('href', /work\?id=doi/);
	await expect(page.locator('.proof')).not.toContainText('\\cite');

	// what it rests on: a result of the other paper, reached by a locator, drawn as a graph
	await expect(page.getByRole('heading', { name: /What it rests on/ })).toBeVisible();
	await expect(page.locator('svg[role="img"] a')).toHaveCount(2);
	await expect(page.getByRole('heading', { name: /Cited without naming a result/ })).toBeVisible();

	// and the trail leads on: every node of the graph is a link to the result it draws
	await page.locator('svg[role="img"] a[href*="2401.00001v2"]').click();
	await expect(page).toHaveURL(/result\?key=arxiv%3A2401\.00001v2%23thm-1\.1/);
});

test('the view says so when nothing is answering', async ({ page }) => {
	await page.goto('/?q=anything&api=http://127.0.0.1:9');
	await expect(page.getByText(/is `weft serve` running\?/).first()).toBeVisible();
});
