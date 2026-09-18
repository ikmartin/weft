import { describe, expect, it } from 'vitest';
import { label, parseKey, workOf } from './keys';

describe('a result key', () => {
	it('names a version, a result inside it, and the work the version belongs to', () => {
		expect(parseKey('arxiv:1709.09864v2#thm-4.1')).toEqual({ version: 'arxiv:1709.09864v2', local: 'thm-4.1', work: 'arxiv:1709.09864' });
	});

	it('leaves a version that is not an arXiv one alone, since a DOI names the work itself', () => {
		expect(workOf('doi:10.1007/s002220050293')).toBe('doi:10.1007/s002220050293');
		expect(parseKey('doi:10.1007/s002220050293#thm-1').work).toBe('doi:10.1007/s002220050293');
	});

	it('is a version alone when it carries no result', () => {
		expect(parseKey('arxiv:2401.00001v1')).toEqual({ version: 'arxiv:2401.00001v1', local: '', work: 'arxiv:2401.00001' });
	});
});

describe('a result read to a reader', () => {
	it('is its taxon and number, and falls back to what the paper called it', () => {
		expect(label({ taxon: 'Theorem', number: '4.1' })).toBe('Theorem 4.1');
		expect(label({ taxon: 'Lemma', number: '' })).toBe('Lemma');
		expect(label({ taxon: '', number: '', local: 'setup' })).toBe('setup');
	});
});
