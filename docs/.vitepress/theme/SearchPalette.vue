<script setup lang="ts">
import { computed, ref, shallowRef, watch } from 'vue'
import { useRouter, withBase } from 'vitepress'
import { ListboxContent, ListboxFilter, ListboxItem, ListboxRoot } from 'reka-ui'
import { Dialog, useColorScheme } from 'frappe-ui'
import MiniSearch from 'minisearch'
import localSearchIndex from '@localSearchIndex'

interface SearchResult {
	id: string
	title: string
	titles: string[]
}

const open = defineModel<boolean>('open', { default: true })
const router = useRouter()
const { toggleColorScheme } = useColorScheme()

const query = ref('')
const index = shallowRef<MiniSearch<SearchResult>>()

// VitePress builds the section index at build time; load it the first time the palette opens.
watch(
	open,
	async (isOpen) => {
		if (!isOpen) {
			query.value = ''
			return
		}
		if (index.value) return

		const data = await localSearchIndex.root()
		index.value = MiniSearch.loadJSON<SearchResult>(data.default, {
			fields: ['title', 'titles', 'text'],
			storeFields: ['title', 'titles'],
		})
	},
	{ immediate: true },
)

const results = computed(() => {
	const text = query.value.trim()
	if (!text || !index.value) return []

	return index.value
		.search(text, { fuzzy: 0.2, prefix: true, boost: { title: 4, text: 2, titles: 1 } })
		.slice(0, 12) as unknown as SearchResult[]
})

function go(result: SearchResult) {
	open.value = false
	router.go(withBase(result.id))
}

function toggleTheme() {
	open.value = false
	toggleColorScheme()
}
</script>

<template>
	<Dialog v-model:open="open" bare size="xl" position="top" padding-top="10vh">
		<template #default>
			<ListboxRoot class="flex flex-col" highlight-on-hover :model-value="null">
				<div class="relative">
					<div class="absolute inset-y-0 left-0 flex items-center pl-4.5">
						<span class="lucide-search h-4 w-4 text-ink-gray-6" />
					</div>
					<ListboxFilter
						v-model="query"
						auto-focus
						aria-label="Search documentation"
						placeholder="Search documentation"
						class="w-full border-none bg-transparent py-3 pl-11.5 pr-4.5 text-base text-ink-gray-7 placeholder-ink-gray-4 focus:ring-0"
						autocomplete="off"
					/>
				</div>

				<ListboxContent class="max-h-96 overflow-auto border-t border-outline-gray-1 p-2.5 dark:border-outline-gray-2">
					<ListboxItem
						v-for="result in results"
						:key="result.id"
						:value="result.id"
						class="flex cursor-pointer flex-col rounded-4 px-2 py-2 outline-none data-[highlighted]:bg-surface-gray-3"
						@select.prevent="go(result)"
					>
						<span class="truncate text-base font-medium text-ink-gray-8">{{ result.title }}</span>
						<span v-if="result.titles.length" class="truncate text-sm text-ink-gray-5">
							{{ result.titles.join(' › ') }}
						</span>
					</ListboxItem>

					<ListboxItem
						v-if="!query"
						value="action:theme"
						class="flex cursor-pointer items-center gap-2.5 rounded-4 px-2 py-2 text-base font-medium text-ink-gray-7 outline-none data-[highlighted]:bg-surface-gray-3"
						@select.prevent="toggleTheme"
					>
						<span class="lucide-sun-moon size-4 text-ink-gray-5" aria-hidden="true" />
						Switch light or dark theme
					</ListboxItem>

					<p v-if="query && index && !results.length" class="my-8 text-center text-base text-ink-gray-6">
						No pages match “{{ query }}”.
					</p>
				</ListboxContent>
			</ListboxRoot>
		</template>
	</Dialog>
</template>
