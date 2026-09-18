<script lang="ts">
	import { page } from '$app/state';
	import { search } from '$lib/api';
	import type { Search } from '$lib/types';

	const asked = $derived(page.url.searchParams.get('q') ?? '');
	let found: Search | null = $state(null);
	let trouble = $state('');

	$effect(() => {
		const q = asked;
		found = null;
		trouble = '';
		if (!q) return;
		search(q)
			.then((s) => (found = s))
			.catch((e: Error) => (trouble = e.message));
	});
</script>

<svelte:head><title>{asked ? `${asked} — weft` : 'weft'}</title></svelte:head>

{#if !asked}
	<h1>A library of mathematical results</h1>
	<p class="quiet">Search for a work by title or author, or open a result by key. Every statement here is its author's, quoted; every edge is one a paper states.</p>
{:else if trouble}
	<p class="trouble">{trouble}</p>
{:else if !found}
	<p class="quiet">asking…</p>
{:else if found.works.length === 0}
	<p class="quiet">Nothing in this corpus answers to “{asked}”.</p>
{:else}
	<h1>{found.works.length} work{found.works.length === 1 ? '' : 's'}</h1>
	<ul class="works">
		{#each found.works as work (work.key)}
			<li>
				<a href="/work?id={encodeURIComponent(work.key)}">{work.title || work.key}</a>
				<div class="quiet">
					{work.authors.join(', ')}{work.year ? ` · ${work.year}` : ''}
					{#if work.versions?.length}· {work.versions.length} version{work.versions.length === 1 ? '' : 's'}{/if}
					{#if work.msc.length}· {work.msc.slice(0, 3).join(' ')}{/if}
				</div>
				<div class="quiet"><code>{work.key}</code></div>
			</li>
		{/each}
	</ul>
{/if}

<style>
	.works {
		list-style: none;
		padding: 0;
	}
	.works li {
		padding: 0.6rem 0;
		border-bottom: 1px solid var(--rule);
	}
</style>
