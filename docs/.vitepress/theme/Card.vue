<script setup lang="ts">
import { withBase } from 'vitepress'

interface CardProps {
	title: string
	link: string
	/** A full Lucide icon class, such as `lucide-server`, so Tailwind finds it in the page. */
	icon?: string
}

const props = defineProps<CardProps>()
const isExternal = /^https?:\/\//.test(props.link)
</script>

<template>
	<a
		class="docs-card"
		:href="isExternal ? link : withBase(link)"
		:target="isExternal ? '_blank' : undefined"
		:rel="isExternal ? 'noopener' : undefined"
	>
		<span v-if="icon" :class="icon" class="docs-card-icon size-5" aria-hidden="true" />
		<span class="docs-card-title">{{ title }}</span>
		<span class="docs-card-text"><slot /></span>
	</a>
</template>
