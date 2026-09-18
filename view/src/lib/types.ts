// The payloads the HTTP API answers with, as `weft/query.py` builds them. One shape per query, named after the route.

export type Edge = { src: string; to: string; origin: 'internal' | 'locator' | 'unspecified'; confidence: number; evidence: string };

export type Result = {
	key: string;
	version: string;
	local: string;
	taxon: string;
	number: string;
	title: string;
	aliases: string[];
	page: string;
	statement?: string;
	proof?: string;
	uses?: Edge[];
	used_by?: Edge[];
};

export type Work = {
	key: string;
	ids: string[];
	title: string;
	authors: string[];
	year: string;
	msc: string[];
	arxiv_category: string;
	depth: number;
	provenance: string;
	citekeys: string[];
	versions?: string[];
};

export type Search = { query: string; works: Work[] };
export type Closure = { key: string; depth: number; closure: Result[]; missing: string[]; unresolved: Edge[] };
export type Dependents = { key: string; used_by: { edge: Edge; result: Result | null }[] };
export type Neighbourhood = {
	found: boolean;
	work: Work;
	versions: { id: string; method: string; numbering: string }[];
	results: Result[];
	cites: string[];
	references: { work: string; citekey: string; text: string; identified_by: string }[];
};
export type Versions = {
	found: boolean;
	work: string;
	versions: { id: string; method: string; numbering: string; extracted_at: string; results: { local: string; taxon: string; number: string }[] }[];
};
