<script setup lang="ts">
import { withBase } from 'vitepress'

interface ScreenshotProps {
	/** Path under `media/<theme>/` without the extension, such as `servers/list`. */
	name: string
	alt: string
	caption?: string
}

const props = defineProps<ScreenshotProps>()
const source = (theme: 'light' | 'dark') => withBase(`/media/${theme}/${props.name}.webp`)
</script>

<template>
	<figure class="docs-media">
		<img class="only-light" :src="source('light')" :alt="alt" loading="lazy" decoding="async" />
		<img class="only-dark" :src="source('dark')" :alt="alt" loading="lazy" decoding="async" />
		<figcaption v-if="caption">{{ caption }}</figcaption>
	</figure>
</template>
