import adapter from '@sveltejs/adapter-static';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vitest/config';

// A single-page app: the corpus is queried over HTTP at runtime and never published whole, so every route falls back to one page and nothing is prerendered. Where the API answers is a runtime choice (src/lib/api.ts), not a build-time one.
export default defineConfig({
	plugins: [
		sveltekit({
			compilerOptions: { runes: ({ filename }) => (filename.split(/[/\\]/).includes('node_modules') ? undefined : true) },
			adapter: adapter({ fallback: 'index.html', strict: false }),
			alias: { $lib: 'src/lib' }
		})
	],
	test: {
		expect: { requireAssertions: true },
		include: ['src/**/*.spec.ts'],
		environment: 'node'
	}
});
