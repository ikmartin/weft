// A citation inside a statement or a proof, as the paper wrote it and as this corpus resolved it.
//
// The text arrives verbatim -- `\cite[Theorem 1.1]{other}` and all -- because a statement whose citations were stripped is a different statement. The linker has already decided what each one points at, and records the locator it matched as the edge's evidence, so the view re-reads the same commands and asks the edges where each one went. A citation the linker did not resolve is shown as the paper printed it, never as a guess.

export type Piece = { kind: 'text'; text: string } | { kind: 'cite'; text: string; postnote: string; citekey: string; href: string | null };

const CITE = /\\(?:cite|parencite|textcite|autocite|citep|citet|footcite)\s*(?:\[([^\]]*)\])?\s*\{([^}]*)\}/g;

/** The same normalisation the linker's evidence went through, as far as a postnote's common forms need: case, tildes, spacing, a trailing stop. */
export function normalise(postnote: string): string {
	return postnote
		.replace(/[~{}]/g, ' ')
		.replace(/\\S|§/g, 'section')
		.replace(/\s+/g, ' ')
		.trim()
		.replace(/\.$/, '')
		.toLowerCase();
}

/** Split text into what to show and what to link, given something that resolves one citation. */
export function pieces(text: string, resolve: (postnote: string, citekey: string) => string | null): Piece[] {
	const out: Piece[] = [];
	let at = 0;
	for (const m of text.matchAll(CITE)) {
		const start = m.index ?? 0;
		if (start > at) out.push({ kind: 'text', text: text.slice(at, start) });
		const postnote = (m[1] ?? '').trim();
		const citekey = (m[2] ?? '').trim();
		out.push({ kind: 'cite', text: postnote || citekey, postnote, citekey, href: resolve(postnote, citekey) });
		at = start + m[0].length;
	}
	if (at < text.length) out.push({ kind: 'text', text: text.slice(at) });
	return out;
}

type Edgeish = { to: string; origin: string; evidence: string };

/** Where a citation went, read off the edges the linker drew from this result: a locator edge carries the locator it matched, and an unresolved one carries the command. */
export function resolver(edges: Edgeish[]): (postnote: string, citekey: string) => string | null {
	const byLocator = new Map<string, string>();
	const byKey = new Map<string, string>();
	for (const e of edges) {
		if (e.origin === 'locator' && e.evidence) byLocator.set(normalise(e.evidence), e.to);
		const m = /^\\cite\{(.+)\}$/.exec(e.evidence);
		if (m) byKey.set(m[1], e.to);
	}
	return (postnote, citekey) => {
		const target = (postnote && byLocator.get(normalise(postnote))) || byKey.get(citekey);
		if (!target) return null;
		return target.includes('#') ? `/result?key=${encodeURIComponent(target)}` : `/work?id=${encodeURIComponent(target)}`;
	};
}
