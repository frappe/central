<script setup lang="ts">
import { withBase } from 'vitepress'
</script>

<template>
	<div class="docs-not-found">
		<p class="docs-airport">404</p>
		<h1>This gate does not exist</h1>
		<p>The page moved, or the link has a typo.</p>
		<a :href="withBase('/')">Go to the overview</a>
	</div>
</template>

<style scoped>
.docs-not-found {
	display: flex;
	flex-direction: column;
	align-items: center;
	justify-content: center;
	gap: 0.75rem;
	min-height: 60vh;
	padding: 1rem;
	text-align: center;
	color: var(--ink-gray-6);
}
.docs-not-found h1 {
	font-size: 1.5rem;
	font-weight: 600;
	color: var(--ink-gray-9);
}
.docs-not-found a {
	color: var(--ink-gray-8);
	text-decoration: underline;
}
</style>
