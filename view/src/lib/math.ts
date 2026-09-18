// MathJax 3, TeX in and SVG out, bundled from the package so nothing loads from a CDN. A corpus holds statements as their authors wrote them, `$…$` and all, which is the only reason this is here.

type MJ = { typesetPromise: (els: Element[]) => Promise<void>; startup: { promise: Promise<void> } };

declare global {
	interface Window {
		MathJax: unknown;
	}
}

let loaded: Promise<MJ> | null = null;

export function ensureMathJax(): Promise<MJ> {
	if (!loaded) {
		window.MathJax = {
			tex: {
				inlineMath: [
					['$', '$'],
					['\\(', '\\)']
				],
				displayMath: [
					['$$', '$$'],
					['\\[', '\\]']
				],
				processEscapes: true,
				packages: { '[+]': ['ams', 'amscd', 'boldsymbol', 'mathtools', 'newcommand', 'color', 'unicode', 'textmacros'] },
				tags: 'none'
			},
			svg: { fontCache: 'global' },
			options: { skipHtmlTags: ['script', 'noscript', 'style', 'textarea', 'code'] },
			startup: { typeset: false }
		};
		loaded = import('mathjax/es5/tex-svg-full.js').then(async () => {
			const mj = window.MathJax as MJ;
			await mj.startup.promise;
			return mj;
		});
	}
	return loaded;
}

// MathJax is not safe to enter twice, so every typeset goes through one queue.
let queue: Promise<unknown> = Promise.resolve();

export async function typeset(el: Element): Promise<void> {
	const mj = await ensureMathJax();
	const next = queue.then(() => mj.typesetPromise([el]));
	queue = next.catch(() => {});
	await next;
}
