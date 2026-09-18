// Reading a result key. `arxiv:1709.09864v2#thm-4.1` names a version and a result inside it; the work is the version without its version suffix, which is what a link back to the paper needs.

export type Parsed = { version: string; local: string; work: string };

const VERSION = /^(arxiv:.+?)(v\d+)$/;

export function parseKey(key: string): Parsed {
	const at = key.indexOf('#');
	const version = at < 0 ? key : key.slice(0, at);
	return { version, local: at < 0 ? '' : key.slice(at + 1), work: workOf(version) };
}

/** The work a version belongs to: an arXiv version number is dropped, anything else already names its work. */
export function workOf(version: string): string {
	const m = VERSION.exec(version);
	return m ? m[1] : version;
}

/** How a result is named to a reader: `Theorem 4.1`, or its local id where the paper numbered nothing. */
export function label(r: { taxon?: string; number?: string; local?: string; key?: string }): string {
	const taxon = r.taxon ?? '';
	const number = r.number ?? '';
	if (taxon && number) return `${taxon} ${number}`;
	if (taxon) return taxon;
	return r.local ?? r.key ?? '';
}

export const ORIGIN: Record<string, string> = {
	internal: 'stated in the same paper',
	locator: 'cited by name',
	unspecified: 'cited without naming a result'
};
