<script lang="ts">
	import { page } from '$app/state';
	import { versions, work } from '$lib/api';
	import { label } from '$lib/keys';
	import Tex from '$lib/components/Tex.svelte';
	import type { Neighbourhood, Versions } from '$lib/types';

	const id = $derived(page.url.searchParams.get('id') ?? '');
	let found: Neighbourhood | null = $state(null);
	let byVersion: Versions | null = $state(null);
	let trouble = $state('');

	$effect(() => {
		const which = id;
		found = null;
		byVersion = null;
		trouble = '';
		if (!which) return;
		work(which)
			.then((w) => (found = w))
			.catch((e: Error) => (trouble = e.message));
		versions(which)
			.then((v) => (byVersion = v))
			.catch(() => {});
	});
</script>

<svelte:head><title>{found?.work.title || id} — weft</title></svelte:head>

{#if trouble}
	<p class="trouble">{trouble}</p>
{:else if !found}
	<p class="quiet">asking…</p>
{:else}
	<h1><Tex text={found.work.title || found.work.key} /></h1>
	<p class="quiet">
		{found.work.authors.join(', ')}{found.work.year ? ` · ${found.work.year}` : ''}
		{#if found.work.msc.length}· {found.work.msc.join(' ')}{/if}
	</p>
	<p class="quiet">{#each found.work.ids as ident (ident)}<code>{ident}</code>&nbsp; {/each}</p>

	<h2>Versions</h2>
	{#if byVersion?.versions?.length}
		{#each byVersion.versions as version (version.id)}
			<div class="version">
				<h3><code>{version.id}</code> <span class="badge">{version.results.length} results</span>{#if version.numbering}<span class="badge">numbering {version.numbering}</span>{/if}</h3>
				<ul class="results">
					{#each version.results as r (r.local)}
						<li><a href="/result?key={encodeURIComponent(version.id + '#' + r.local)}">{label(r)}</a> <span class="quiet"><code>{r.local}</code></span></li>
					{/each}
				</ul>
			</div>
		{/each}
	{:else}
		<p class="quiet">No version of this work has been extracted here; the corpus knows it by reference only.</p>
	{/if}

	<h2>Cites</h2>
	{#if found.cites.length}
		<ul class="cites">
			{#each found.cites as cited (cited)}
				<li><a href="/work?id={encodeURIComponent(cited)}">{cited}</a></li>
			{/each}
		</ul>
	{:else}
		<p class="quiet">Nothing extracted here cites another work.</p>
	{/if}

	<h2>References <span class="quiet">({found.references.length})</span></h2>
	<ul class="refs">
		{#each found.references.slice(0, 200) as ref, i (ref.citekey + i)}
			<li>
				{#if ref.work}<a href="/work?id={encodeURIComponent(ref.work)}">{ref.work}</a>{/if}
				<span class="quiet">{ref.text}</span>
				{#if ref.identified_by}<span class="badge">by {ref.identified_by}</span>{/if}
			</li>
		{/each}
	</ul>
{/if}

<style>
	h3 {
		font-size: 0.95rem;
		font-weight: 600;
		margin: 1rem 0 0.3rem;
	}
	ul {
		list-style: none;
		padding: 0;
		margin: 0;
	}
	.results li,
	.cites li,
	.refs li {
		padding: 0.25rem 0;
		border-bottom: 1px solid var(--rule);
	}
	.refs li {
		font-size: 0.9em;
	}
</style>
