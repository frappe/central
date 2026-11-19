<script setup lang="ts">
import { withBase } from 'vitepress'

interface ClipProps {
	/** Path under `media/<theme>/` without the extension, such as `servers/create`. */
	name: string
	/** Describes what the recording shows, for readers who cannot see it. */
	alt: string
	caption?: string
}

const props = defineProps<ClipProps>()
const file = (theme: 'light' | 'dark', extension: string) => withBase(`/media/${theme}/${props.name}.${extension}`)
</script>

<template>
	<figure class="docs-media">
		<video
			v-for="theme in (['light', 'dark'] as const)"
			:key="theme"
			:class="`only-${theme}`"
			:src="file(theme, 'mp4')"
			:poster="file(theme, 'webp')"
			:aria-label="alt"
			autoplay
			muted
			loop
			playsinline
			controls
			preload="metadata"
		/>
		<figcaption v-if="caption">{{ caption }}</figcaption>
	</figure>
</template>
