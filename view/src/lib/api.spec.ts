import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, ask, DEFAULT_API } from './api';

function answering(status: number, payload: unknown): URL[] {
	const asked: URL[] = [];
	vi.stubGlobal('fetch', (url: URL) => {
		asked.push(url);
		return Promise.resolve({ ok: status < 400, status, statusText: String(status), json: () => Promise.resolve(payload) } as Response);
	});
	return asked;
}

afterEach(() => vi.unstubAllGlobals());

describe('asking the corpus', () => {
	it('passes a key as a query parameter, since a key carries # and /', async () => {
		const asked = answering(200, { key: 'x' });
		await ask('/result', { key: 'arxiv:1709.09864v2#thm-4.1' }, DEFAULT_API);
		expect(asked[0].pathname).toBe('/result');
		expect(asked[0].searchParams.get('key')).toBe('arxiv:1709.09864v2#thm-4.1');
		expect(asked[0].hash).toBe('');
	});

	it('leaves out a parameter that was not given, so a default stays the server’s to choose', async () => {
		const asked = answering(200, {});
		await ask('/closure', { key: 'k', depth: undefined, text: '' }, DEFAULT_API);
		expect([...asked[0].searchParams.keys()]).toEqual(['key']);
	});

	it('turns the API’s own error into one, with its status', async () => {
		answering(404, { error: 'no such result' });
		await expect(ask('/result', { key: 'nope' }, DEFAULT_API)).rejects.toThrow(new ApiError('no such result', 404));
	});

	it('says which address did not answer when nothing is listening', async () => {
		vi.stubGlobal('fetch', () => Promise.reject(new Error('refused')));
		await expect(ask('/counts', {}, 'http://127.0.0.1:9')).rejects.toThrow(/127\.0\.0\.1:9 — is `weft serve` running\?/);
	});
});
