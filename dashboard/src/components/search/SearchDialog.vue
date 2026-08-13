<script setup lang="ts">
import { Dialog } from 'frappe-ui'
import {
	ListboxContent,
	ListboxFilter,
	ListboxGroup,
	ListboxGroupLabel,
	ListboxItem,
	ListboxRoot,
} from 'reka-ui'
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import type { SearchItem } from './index'
import { useSearchIndex } from './index'
import { filterIndex, highlightMatch } from './utils'

const open = defineModel<boolean>('open', { default: false })

const router = useRouter()
const query = ref('')
const searchIndex = useSearchIndex()

const filtered = computed(() => filterIndex(searchIndex.value, query.value))
const hasResults = computed(() => Object.keys(filtered.value).length > 0)

watch(open, (isOpen) => {
	if (!isOpen) query.value = ''
})

function select(item: SearchItem): void {
	if (item.route) router.push(item.route)
	else item.onSelect?.()
	open.value = false
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
						placeholder="Search"
						class="w-full border-none bg-transparent py-3 pl-11.5 pr-4.5 text-base text-ink-gray-7 placeholder-ink-gray-4 focus:ring-0"
						autocomplete="off"
					/>
				</div>

				<ListboxContent
					class="max-h-96 overflow-auto border-t border-outline-gray-1"
				>
					<ListboxGroup
						v-for="(group, name) in filtered"
						:key="name"
						class="mb-2 mt-4.5 first:mt-3"
					>
						<ListboxGroupLabel
							class="mb-2.5 block px-4.5 text-base text-ink-gray-5"
						>
							{{ name }}
						</ListboxGroupLabel>

						<div
							v-for="item in group.items"
							:key="`${name}-${item.name}`"
							class="px-2.5"
						>
							<ListboxItem
								:value="`${name}-${item.name}`"
								class="flex w-full min-w-0 items-center gap-2 rounded-4 px-2 py-2 text-base font-medium text-ink-gray-7 outline-none data-[highlighted]:bg-surface-gray-3"
								@select="select(item)"
							>
								<span
									:class="item.icon"
									class="size-4 shrink-0 text-ink-gray-6"
								/>
								<span
									class="min-w-0 flex-1 truncate"
									v-html="highlightMatch(item.name, query)"
								/>
								<span
									v-if="item.description"
									class="shrink-0 truncate pl-2 text-xs font-normal text-ink-gray-5"
								>
									{{ item.description }}
								</span>
							</ListboxItem>
						</div>
					</ListboxGroup>

					<div
						v-if="query && !hasResults"
						class="my-8 text-center text-base text-ink-gray-6"
					>
						No results for "<b class="text-ink-gray-9">{{ query }}</b
						>"
					</div>
				</ListboxContent>

				<div
					class="mt-2 flex items-center justify-between border-t border-outline-gray-1 px-2.5 py-2 text-xs text-ink-gray-6"
				>
					<div class="flex items-center gap-4">
						<div class="flex items-center gap-1">
							<kbd><span class="lucide-arrow-down size-4" /></kbd>
							<kbd><span class="lucide-arrow-up size-4" /></kbd>
							<span class="ml-1">to navigate</span>
						</div>
						<div class="flex items-center gap-1">
							<kbd><span class="lucide-corner-down-left size-4" /></kbd>
							<span class="ml-1">to select</span>
						</div>
						<div class="flex items-center gap-1">
							<kbd class="px-1 text-sm">esc</kbd>
							<span class="ml-1">to close</span>
						</div>
					</div>
					<div class="flex items-center gap-1">
						<kbd>
							<span class="lucide-command h-3 w-3" />
							<span class="text-sm">K</span>
						</kbd>
						<span class="ml-1">to open</span>
					</div>
				</div>
			</ListboxRoot>
		</template>
	</Dialog>
</template>

<style scoped>
:deep(mark) {
	background: var(--surface-gray-3);
	color: var(--ink-gray-9);
	font-weight: 500;
}

/* Matches the frappe-ui docs command palette's key caps. */
kbd {
	@apply inline-flex items-center gap-0.5 whitespace-nowrap rounded-1;
	@apply bg-surface-gray-2 p-0.5 font-sans font-medium text-ink-gray-5;
	font-size: 11px;
	line-height: normal;
	letter-spacing: 0.02em;
}
</style>
