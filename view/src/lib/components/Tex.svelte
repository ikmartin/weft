<script lang="ts">
	// A paper's own text, typeset where it is shown, with its citations linked where this corpus resolved them.
	//
	// The source is kept, never stripped: a statement whose maths were dropped is a different statement, and one whose citations were dropped hides what it rests on.
	import { pieces, type Piece } from '$lib/cites';
	import { typeset } from '$lib/math';

	let {
		text,
		block = false,
		resolve
	}: { text: string; block?: boolean; resolve?: (postnote: string, citekey: string) => string | null } = $props();

	let el: HTMLElement | undefined = $state();
	const parts: Piece[] = $derived(resolve ? pieces(text, resolve) : [{ kind: 'text', text }]);

	$effect(() => {
		const node = el;
		void parts;
		if (!node) return;
		void typeset(node);
	});
</script>

<svelte:element this={block ? 'div' : 'span'} class="tex" bind:this={el}>
	{#each parts as part, i (i)}
		{#if part.kind === 'text'}{part.text}{:else if part.href}<a class="cite" href={part.href}>{part.text}</a>{:else}<span class="cite unresolved" title="nothing in this corpus answers to this citation">{part.text}</span>{/if}
	{/each}
</svelte:element>

<style>
	.tex {
		white-space: pre-wrap;
		line-height: 1.55;
	}
	.cite {
		white-space: nowrap;
	}
	.cite::before {
		content: '[';
	}
	.cite::after {
		content: ']';
	}
	.unresolved {
		color: var(--dim);
		border-bottom: 1px dotted var(--rule);
	}
</style>
