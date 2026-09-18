import { defineConfig } from '@playwright/test';

// Two servers, because the view and the corpus are two processes by design: `weft serve` answers over HTTP, and the built app asks it. The corpus is the committed synthetic one, indexed first, so this test needs no network and no crawl.
const API = 8793;
const APP = 4179;

export default defineConfig({
	testDir: 'tests',
	fullyParallel: false,
	workers: 1,
	use: { baseURL: `http://127.0.0.1:${APP}` },
	webServer: [
		{
			command: `cd ../demos/synthetic && uv run --project .. weft index rebuild && uv run --project .. weft serve --port ${API}`,
			port: API,
			reuseExistingServer: !process.env.CI,
			stdout: 'ignore'
		},
		{
			command: `npm run build && npm run preview -- --port ${APP} --strictPort --host 127.0.0.1`,
			port: APP,
			reuseExistingServer: !process.env.CI,
			stdout: 'ignore'
		}
	]
});
