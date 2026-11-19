<script setup lang="ts">
import { theme } from 'frappe-ui/vitepress'
import { useData, useRoute } from 'vitepress'
import { nextTick, onMounted, watch } from 'vue'

const Layout = theme.Layout
const route = useRoute()
const { theme: themeConfig } = useData()

// The theme's <main> has no id, so the skip link would have no target.
async function markMainContent() {
	await nextTick()
	const main = document.querySelector('main')
	if (!main) return
	main.id = 'main-content'
	main.tabIndex = -1
}

onMounted(markMainContent)
watch(() => route.path, markMainContent)
</script>

<template>
	<a class="skip-link" href="#main-content">Skip to content</a>
	<Layout>
		<template #actions>
			<a v-if="themeConfig.consoleUrl" class="console-link" :href="themeConfig.consoleUrl" target="_blank" rel="noopener">
				Open console <span aria-hidden="true">↗</span>
			</a>
		</template>
	</Layout>
</template>
