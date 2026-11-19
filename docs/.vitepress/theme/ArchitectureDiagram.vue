<script setup lang="ts">
interface ArchitectureDiagramProps {
	/** `generations` compares v1 containers with v2 servers. `stack` shows what runs inside a v2 server. */
	variant: 'generations' | 'stack'
}

defineProps<ArchitectureDiagramProps>()
</script>

<template>
	<figure v-if="variant === 'generations'" class="docs-diagram docs-diagram-generations" aria-label="Frappe Cloud v1 runs your bench as a container on a shared server. Frappe Cloud v2 gives you a server of your own.">
		<div class="docs-diagram-panel">
			<p class="docs-diagram-eyebrow">v1 · Containers</p>
			<div class="docs-diagram-box docs-diagram-host">
				<span class="docs-diagram-label">Server managed by Frappe</span>
				<div class="docs-diagram-row">
					<span class="docs-diagram-chip is-yours">Your bench</span>
					<span class="docs-diagram-chip">Another team's bench</span>
					<span class="docs-diagram-chip">Another team's bench</span>
				</div>
			</div>
			<div class="docs-diagram-box">
				<span class="docs-diagram-label">Shared database server</span>
			</div>
			<p class="docs-diagram-note">You choose a bench group, then a shared or dedicated server.</p>
		</div>

		<div class="docs-diagram-panel">
			<p class="docs-diagram-eyebrow">v2 · Servers</p>
			<div class="docs-diagram-box docs-diagram-host is-yours">
				<span class="docs-diagram-label">Your server, a virtual machine</span>
				<div class="docs-diagram-row">
					<span class="docs-diagram-chip">Ubuntu</span>
					<span class="docs-diagram-or">or</span>
					<span class="docs-diagram-chip is-yours">Pilot → benches → sites</span>
				</div>
			</div>
			<div class="docs-diagram-box">
				<span class="docs-diagram-label">No other team runs inside it</span>
			</div>
			<p class="docs-diagram-note">You choose a server. Everything inside it is yours.</p>
		</div>
	</figure>

	<figure v-else class="docs-diagram docs-diagram-stack" aria-label="Central, the console, sends requests to Atlas in the Mumbai region. Atlas runs your server from an image that Cargo builds. Inside a Frappe server, Pilot runs a bench with sites.">
		<div class="docs-diagram-box">
			<span class="docs-diagram-label">Central <span class="docs-diagram-detail">· the console</span></span>
			<span class="docs-diagram-detail">Teams, roles, sign-in, billing</span>
		</div>
		<span class="docs-diagram-arrow" aria-hidden="true">↓</span>
		<div class="docs-diagram-box docs-diagram-host">
			<span class="docs-diagram-label">Region <span class="docs-airport">BOM</span> Mumbai</span>
			<div class="docs-diagram-row">
				<span class="docs-diagram-chip">Atlas · servers, network, proxy</span>
				<span class="docs-diagram-chip">Cargo · images, storage</span>
			</div>
			<div class="docs-diagram-box docs-diagram-host is-yours">
				<span class="docs-diagram-label">Your server <code>erp-production</code></span>
				<div class="docs-diagram-box">
					<span class="docs-diagram-label">Pilot</span>
					<div class="docs-diagram-box">
						<span class="docs-diagram-label">Bench</span>
						<div class="docs-diagram-row">
							<span class="docs-diagram-chip">erp.bom.frappe.cloud</span>
							<span class="docs-diagram-chip">hr.bom.frappe.cloud</span>
						</div>
						<span class="docs-diagram-detail">Each site has its own database and apps</span>
					</div>
				</div>
			</div>
		</div>
	</figure>
</template>

<style scoped>
.docs-diagram {
	margin: 1.5rem 0;
	font-size: 0.8125rem;
}
.docs-diagram-generations {
	display: grid;
	grid-template-columns: repeat(auto-fit, minmax(16rem, 1fr));
	gap: 1rem;
}
.docs-diagram-stack {
	display: flex;
	flex-direction: column;
	align-items: stretch;
	gap: 0.5rem;
}
.docs-diagram-panel {
	display: flex;
	flex-direction: column;
	gap: 0.5rem;
	padding: 1rem;
	border: 1px solid var(--outline-gray-2);
	border-radius: 0.75rem;
	background: var(--surface-gray-1);
}
.docs-diagram-eyebrow {
	margin: 0;
	font-size: 0.75rem;
	font-weight: 600;
	letter-spacing: 0.04em;
	text-transform: uppercase;
	color: var(--ink-gray-5);
}
.docs-diagram-box {
	display: flex;
	flex-direction: column;
	gap: 0.5rem;
	padding: 0.625rem 0.75rem;
	border: 1px solid var(--outline-gray-2);
	border-radius: 0.5rem;
	background: var(--surface-base, var(--surface-white));
}
.docs-diagram-host {
	border-style: dashed;
}
.docs-diagram-box.is-yours,
.docs-diagram-chip.is-yours {
	border-color: var(--ink-blue-5);
	border-style: solid;
}
.docs-diagram-label {
	font-weight: 600;
	color: var(--ink-gray-8);
}
.docs-diagram-detail,
.docs-diagram-note {
	margin: 0;
	color: var(--ink-gray-5);
}
.docs-diagram-row {
	display: flex;
	flex-wrap: wrap;
	align-items: center;
	gap: 0.375rem;
}
.docs-diagram-chip {
	padding: 0.125rem 0.5rem;
	border: 1px solid var(--outline-gray-2);
	border-radius: 0.375rem;
	background: var(--surface-gray-1);
	color: var(--ink-gray-7);
	white-space: nowrap;
}
.docs-diagram-or {
	color: var(--ink-gray-5);
}
.docs-diagram-arrow {
	align-self: center;
	color: var(--ink-gray-4);
}
</style>
