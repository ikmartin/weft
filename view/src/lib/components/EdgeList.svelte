<script lang="ts">
	// The edges at one end of a result, each said to be what it is. A locator edge names a result and is a link; an unspecified one names a work and is a link to the work, because that is as far as the paper went.
	import { ORIGIN, parseKey } from '$lib/keys';
	import type { Edge } from '$lib/types';

	let {
		edges,
		empty = 'none',
		labels = {},
		source = false
	}: { edges: Edge[]; empty?: string; labels?: Record<string, string>; source?: boolean } = $props();
</script>

{#if edges.length === 0}
	<p class="quiet">{empty}</p>
{:else}
	<ul>
		{#each edges as edge (edge.src + edge.to + edge.evidence)}
			<li>
				{#if edge.to.includes('#')}
					<a href="/result?key={encodeURIComponent(edge.to)}">{labels[edge.to] ?? parseKey(edge.to).local}</a>
					<span class="quiet"><code>{parseKey(edge.to).version}</code></span>
				{:else}
					<a href="/work?id={encodeURIComponent(edge.to)}">{edge.to}</a>
				{/if}
				<span class="badge">{ORIGIN[edge.origin] ?? edge.origin}</span>
				{#if edge.evidence}<code>{edge.evidence}</code>{/if}
				{#if source}<span class="quiet">cited by <a href="/result?key={encodeURIComponent(edge.src)}">{labels[edge.src] ?? parseKey(edge.src).local}</a></span>{/if}
			</li>
		{/each}
	</ul>
{/if}

<style>
	ul {
		list-style: none;
		margin: 0;
		padding: 0;
	}
	li {
		padding: 0.35rem 0;
		border-bottom: 1px solid var(--rule);
		display: flex;
		gap: 0.6rem;
		align-items: baseline;
		flex-wrap: wrap;
	}
	code {
		font-size: 0.85em;
		color: var(--dim);
	}
</style>
