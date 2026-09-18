import { describe, expect, it } from 'vitest';
import { normalise, pieces, resolver } from './cites';

const EDGES = [
	{ to: 'arxiv:2401.00001v2#thm-1.1', origin: 'locator', evidence: 'theorem 1.1' },
	{ to: 'doi:10.4171/synth.0003', origin: 'unspecified', evidence: '\\cite{third}' }
];

describe('a citation in a proof', () => {
	it('is linked where the linker resolved it, to the result it named', () => {
		const out = pieces('by \\cite[Theorem 1.1]{other} and nothing else', resolver(EDGES));
		expect(out.map((p) => p.kind)).toEqual(['text', 'cite', 'text']);
		const cite = out[1];
		expect(cite.kind === 'cite' && cite.href).toBe('/result?key=arxiv%3A2401.00001v2%23thm-1.1');
		expect(cite.kind === 'cite' && cite.text).toBe('Theorem 1.1');
	});

	it('links to the whole work where the paper named no result', () => {
		const [cite] = pieces('\\cite{third}', resolver(EDGES));
		expect(cite.kind === 'cite' && cite.href).toBe('/work?id=doi%3A10.4171%2Fsynth.0003');
	});

	it('is left as the paper printed it where nothing resolved it, rather than guessed at', () => {
		const [cite] = pieces('\\cite[Lemma 9]{nobody}', resolver(EDGES));
		expect(cite.kind === 'cite' && cite.href).toBe(null);
		expect(cite.kind === 'cite' && cite.text).toBe('Lemma 9');
	});

	it('leaves text that carries no citation alone, maths and all', () => {
		const text = 'Let $C$ be a curve with $H^1(C, \\omega_C) = 0$.';
		expect(pieces(text, resolver([]))).toEqual([{ kind: 'text', text }]);
	});

	it('reads a locator the way the linker recorded it', () => {
		expect(normalise('Theorem~1.1.')).toBe('theorem 1.1');
		expect(normalise('  \\S 4 ')).toBe('section 4');
	});
});
