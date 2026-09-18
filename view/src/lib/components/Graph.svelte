<script lang="ts">
	// The closure of one result, laid out by force and drawn as a plain SVG: what a paper leans on, at a glance, with every node a link.
	//
	// Only edges among the results shown are drawn -- a citation naming a whole work has no node here, and is reported beneath the graph rather than invented as one.
	import { forceCenter, forceLink, forceManyBody, forceSimulation, type SimulationLinkDatum, type SimulationNodeDatum } from 'd3-force';
	import { label, parseKey } from '$lib/keys';
	import type { Closure, Edge } from '$lib/types';

	let { root, rootLabel = '', of, edges }: { root: string; rootLabel?: string; of: Closure; edges: Edge[] } = $props();

	type Node = SimulationNodeDatum & { id: string; text: string; root: boolean };
	type Link = SimulationLinkDatum<Node> & { origin: string };

	const W = 640;
	const H = 320;
	const MIN_W = 520;
	const MIN_H = 220;

	let nodes: Node[] = $state([]);
	let links: Link[] = $state([]);
	let box = $state(`0 0 ${W} ${H}`);

	$effect(() => {
		const shown = new Map<string, Node>();
		shown.set(root, { id: root, text: rootLabel || parseKey(root).local, root: true });
		for (const r of of.closure) shown.set(r.key, { id: r.key, text: label(r) || parseKey(r.key).local, root: false });
		// two papers each state a Theorem 1.1, so a name that repeats carries the version that owns it
		const seen = new Map<string, number>();
		for (const n of shown.values()) seen.set(n.text, (seen.get(n.text) ?? 0) + 1);
		for (const n of shown.values()) if ((seen.get(n.text) ?? 0) > 1) n.text = `${n.text} · ${parseKey(n.id).version}`;
		const drawn: Link[] = [];
		for (const e of edges) if (shown.has(e.src) && shown.has(e.to)) drawn.push({ source: shown.get(e.src)!, target: shown.get(e.to)!, origin: e.origin });
		const list = [...shown.values()];
		const sim = forceSimulation(list)
			.force('charge', forceManyBody().strength(-260))
			.force('link', forceLink<Node, Link>(drawn).distance(90).strength(0.7))
			.force('centre', forceCenter(W / 2, H / 2))
			.stop();
		for (let i = 0; i < 220; i++) sim.tick();
		for (const n of list) {
			n.x = Math.max(40, Math.min(W - 40, n.x ?? W / 2));
			n.y = Math.max(20, Math.min(H - 20, n.y ?? H / 2));
		}
		// cropped to what it actually drew, so two nodes do not sit in a screenful of nothing -- but never below the field a label was sized for, or the crop becomes a magnifying glass
		const pad = 40;
		const xs = list.map((n) => n.x ?? 0);
		const ys = list.map((n) => n.y ?? 0);
		const w = Math.max(MIN_W, Math.max(...xs) - Math.min(...xs) + 2 * pad);
		const h = Math.max(MIN_H, Math.max(...ys) - Math.min(...ys) + 2 * pad);
		const cx = (Math.min(...xs) + Math.max(...xs)) / 2;
		const cy = (Math.min(...ys) + Math.max(...ys)) / 2;
		box = `${cx - w / 2} ${cy - h / 2} ${w} ${h}`;
		nodes = list;
		links = drawn;
	});
</script>

<svg viewBox={box} role="img" aria-label="the dependency graph of this result">
	{#each links as link, i (i)}
		{@const a = link.source as Node}
		{@const b = link.target as Node}
		<line x1={a.x} y1={a.y} x2={b.x} y2={b.y} class={link.origin} />
	{/each}
	{#each nodes as node (node.id)}
		<a href="/result?key={encodeURIComponent(node.id)}">
			<!-- a node is a target the size of a fingertip, not the size of its dot -->
			<circle class="hit" cx={node.x} cy={node.y} r="18" />
			<circle cx={node.x} cy={node.y} r={node.root ? 7 : 5} class:root={node.root} />
			<text x={node.x} y={(node.y ?? 0) - 11} text-anchor="middle">{node.text}</text>
		</a>
	{/each}
</svg>

<style>
	svg {
		width: 100%;
		height: auto;
		background: var(--panel);
		border: 1px solid var(--rule);
		border-radius: 6px;
	}
	line {
		stroke: var(--dim);
		stroke-width: 1.2;
	}
	line.locator {
		stroke-dasharray: 4 3;
	}
	circle {
		fill: var(--link);
	}
	circle.root {
		fill: var(--fg);
	}
	circle.hit {
		fill: transparent;
	}
	text {
		font-size: 10px;
		fill: var(--fg);
		font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
	}
</style>
