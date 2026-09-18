<script lang="ts">
	import { page } from '$app/state';
	import { closure, dependents, result } from '$lib/api';
	import EdgeList from '$lib/components/EdgeList.svelte';
	import Graph from '$lib/components/Graph.svelte';
	import Tex from '$lib/components/Tex.svelte';
	import { resolver } from '$lib/cites';
	import { label, ORIGIN, parseKey } from '$lib/keys';
	import type { Closure, Dependents, Edge, Result } from '$lib/types';

	const key = $derived(page.url.searchParams.get('key') ?? '');
	let found: Result | null = $state(null);
	let deep: Closure | null = $state(null);
	let used: Dependents | null = $state(null);
	let trouble = $state('');

	$effect(() => {
		const which = key;
		found = null;
		deep = null;
		used = null;
		trouble = '';
		if (!which) return;
		result(which)
			.then((r) => (found = r))
			.catch((e: Error) => (trouble = e.message));
		closure(which, 6, false)
			.then((c) => (deep = c))
			.catch(() => {});
		dependents(which)
			.then((d) => (used = d))
			.catch(() => {});
	});

	// how each result is named, so an edge reads `Theorem 1.1` rather than a slug; what the closure and the dependents already told us is enough
	function naming(c: Closure | null, d: Dependents | null, r: Result | null): Record<string, string> {
		const out: Record<string, string> = {};
		if (r) out[r.key] = label(r);
		for (const r of c?.closure ?? []) out[r.key] = label(r);
		for (const u of d?.used_by ?? []) if (u.result) out[u.edge.src] = label(u.result);
		return out;
	}
	const named = $derived(naming(deep, used, found));

	// a citation inside the text points where the linker sent it
	const drawn = (r: Result | null): Edge[] => r?.uses ?? [];
	const cites = $derived(resolver(drawn(found)));

	// the graph draws the edges of everything it shows, which means asking each dependency for its own
	let reach: Edge[] = $state([]);
	$effect(() => {
		const c = deep;
		const r = found;
		if (!c || !r) return;
		let stale = false;
		Promise.all(c.closure.map((d) => result(d.key).catch(() => null)))
			.then((all) => {
				if (stale) return;
				reach = [...(r.uses ?? []), ...all.flatMap((d) => d?.uses ?? [])];
			})
			.catch(() => {});
		return () => {
			stale = true;
		};
	});
</script>

<svelte:head><title>{found ? label(found) : key} — weft</title></svelte:head>

{#if trouble}
	<p class="trouble">{trouble}</p>
{:else if !found}
	<p class="quiet">asking…</p>
{:else}
	<h1>{label(found)}{#if found.title}: <Tex text={found.title} />{/if}</h1>
	<p class="quiet">
		<a href="/work?id={encodeURIComponent(parseKey(found.key).work)}">{parseKey(found.key).work}</a>
		· <code>{found.version}</code>
		{#if found.page}· p. {found.page}{/if}
		{#if found.aliases.length}· also {#each found.aliases as alias, i (alias)}{#if i}, {/if}<code>{alias}</code>{/each}{/if}
	</p>

	{#if found.statement}
		<div class="panel"><Tex text={found.statement} block resolve={cites} /></div>
	{/if}

	{#if found.proof}
		<h2>Proof <span class="quiet">as the paper gives it</span></h2>
		<div class="panel proof"><Tex text={found.proof} block resolve={cites} /></div>
	{:else}
		<p class="quiet">This corpus keeps no proof for this result.</p>
	{/if}

	<h2>Uses</h2>
	<EdgeList edges={found.uses ?? []} empty="This result states no dependency." labels={named} />

	<h2>Used by</h2>
	{#if used?.used_by?.length}
		<ul class="used">
			{#each used.used_by as u (u.edge.src + u.edge.evidence)}
				<li>
					<a href="/result?key={encodeURIComponent(u.edge.src)}">{u.result ? label(u.result) : u.edge.src}</a>
					<span class="quiet"><code>{parseKey(u.edge.src).version}</code></span>
					<span class="badge">{ORIGIN[u.edge.origin] ?? u.edge.origin}</span>
				</li>
			{/each}
		</ul>
	{:else}
		<p class="quiet">Nothing extracted here uses this result.</p>
	{/if}

	{#if deep && deep.closure.length}
		<h2>What it rests on <span class="quiet">({deep.closure.length} result{deep.closure.length === 1 ? '' : 's'}, to depth {deep.depth})</span></h2>
		<Graph root={found.key} rootLabel={label(found)} of={deep} edges={reach} />
		<ul class="used">
			{#each deep.closure as dep (dep.key)}
				<li><a href="/result?key={encodeURIComponent(dep.key)}">{label(dep)}</a> <span class="quiet"><code>{dep.version}</code></span></li>
			{/each}
		</ul>
	{/if}

	{#if deep?.unresolved?.length}
		<h2>Cited without naming a result <span class="quiet">({deep.unresolved.length})</span></h2>
		<p class="quiet">A citation with no locator names a whole work, so the trail ends here rather than being guessed at.</p>
		<EdgeList edges={deep.unresolved} labels={named} source />
	{/if}
{/if}

<style>
	.proof {
		font-size: 0.95em;
	}
	ul.used {
		list-style: none;
		padding: 0;
		margin: 0.4rem 0 0;
	}
	ul.used li {
		padding: 0.3rem 0;
		border-bottom: 1px solid var(--rule);
		display: flex;
		gap: 0.6rem;
		align-items: baseline;
		flex-wrap: wrap;
	}
</style>
