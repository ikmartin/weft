<script lang="ts">
	import { page } from '$app/state';
	import { apiBase, counts, DEFAULT_API } from '$lib/api';
	import '../app.css';

	let { children } = $props();

	const base = $derived(apiBase(page.url));
	let held: Record<string, number> | null = $state(null);
	let trouble = $state('');

	$effect(() => {
		void base;
		counts()
			.then((c) => {
				held = c;
				trouble = '';
			})
			.catch((e: Error) => {
				held = null;
				trouble = e.message;
			});
	});

	let asked = $state('');
</script>

<header>
	<a class="mark" href="/">weft</a>
	<form
		onsubmit={(e) => {
			e.preventDefault();
			if (asked.trim()) location.href = `/?q=${encodeURIComponent(asked.trim())}`;
		}}
	>
		<input bind:value={asked} placeholder="a title, or an author" aria-label="search the corpus" />
	</form>
	<span class="quiet">
		{#if held}
			{held.works} works · {held.versions} versions · {held.results} results · {held.edges} edges
		{:else}
			{base === DEFAULT_API ? '' : base}
		{/if}
	</span>
</header>

{#if trouble}
	<p class="trouble">{trouble}</p>
{/if}

<main>
	{@render children()}
</main>

<footer class="quiet">Read-only, and local: this view asks <code>{base}</code>. A corpus holds other people's papers.</footer>

<style>
	header {
		display: flex;
		gap: 1rem;
		align-items: center;
		padding: 0.8rem 1.2rem;
		border-bottom: 1px solid var(--rule);
		flex-wrap: wrap;
	}
	.mark {
		font-weight: 600;
		letter-spacing: 0.02em;
		text-decoration: none;
	}
	form {
		flex: 1 1 18rem;
	}
	input {
		width: 100%;
		padding: 0.4rem 0.6rem;
		border: 1px solid var(--rule);
		border-radius: 4px;
		background: var(--bg);
		color: inherit;
		font: inherit;
	}
	main {
		padding: 1.4rem 1.2rem 3rem;
		max-width: 60rem;
	}
	footer {
		padding: 1rem 1.2rem 2rem;
		border-top: 1px solid var(--rule);
		font-size: 0.85em;
	}
	.trouble {
		margin: 0;
		padding: 0.6rem 1.2rem;
		background: var(--warn);
	}
</style>
