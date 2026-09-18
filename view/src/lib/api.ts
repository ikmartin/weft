// The one place that knows where the corpus is answering.
//
// `weft serve` is read-only and local, so the view holds no credentials and no session: an address, a fetch, and the payload as it came. The address is `?api=` in the URL, else what was last used, else the server's own default -- which is the case that matters, since the usual way in is `weft serve` in one terminal and this in another.

import type { Closure, Dependents, Neighbourhood, Result, Search, Versions } from '$lib/types';

export const DEFAULT_API = 'http://127.0.0.1:8791';
const REMEMBERED = 'weft:api';

export function apiBase(url?: URL): string {
	const asked = url?.searchParams.get('api');
	if (asked) {
		if (typeof localStorage !== 'undefined') localStorage.setItem(REMEMBERED, asked);
		return asked.replace(/\/$/, '');
	}
	if (typeof localStorage !== 'undefined') return (localStorage.getItem(REMEMBERED) ?? DEFAULT_API).replace(/\/$/, '');
	return DEFAULT_API;
}

export class ApiError extends Error {
	constructor(
		message: string,
		readonly status: number
	) {
		super(message);
	}
}

/** One GET against the API. A key carries `#` and `/`, so everything goes as a query parameter and never in the path. */
export async function ask<T>(route: string, params: Record<string, string | number | boolean | undefined> = {}, base = apiBase()): Promise<T> {
	const url = new URL(base + route);
	for (const [name, value] of Object.entries(params)) if (value !== undefined && value !== '') url.searchParams.set(name, String(value));
	let response: Response;
	try {
		response = await fetch(url);
	} catch {
		throw new ApiError(`no answer from ${base} — is \`weft serve\` running?`, 0);
	}
	const payload = await response.json().catch(() => ({ error: response.statusText }));
	if (!response.ok) throw new ApiError(String(payload.error ?? response.statusText), response.status);
	return payload as T;
}

export const search = (text: string, limit = 25) => ask<Search>('/search', { q: text, limit });
export const result = (key: string) => ask<Result>('/result', { key });
export const closure = (key: string, depth = 6, text = false) => ask<Closure>('/closure', { key, depth, text });
export const dependents = (key: string) => ask<Dependents>('/dependents', { key, text: true });
export const work = (id: string) => ask<Neighbourhood>('/work', { id });
export const versions = (id: string) => ask<Versions>('/versions', { id });
export const counts = () => ask<Record<string, number>>('/counts');
