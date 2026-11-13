<script setup lang="ts">
import { Button } from 'frappe-ui'
import { computed, onMounted, useTemplateRef } from 'vue'
import SupportAnswers from '@/components/support/SupportAnswers.vue'
import SupportSearchInput from '@/components/support/SupportSearchInput.vue'
import type {
	SupportArticle,
	SupportContext,
	SupportRelatedTicket,
	SupportTicket,
} from '@/composables/useSupport'
import { getSupportServer } from '@/composables/useSupport'
import type { ContactAction } from '@/composables/useSupportAnswers'
import { isMac } from '@/lib/platform'

interface Props {
	context: SupportContext
	action: ContactAction
	loading: boolean
	error: boolean
	articles: SupportArticle[]
	tickets: SupportRelatedTicket[]
	openTickets: SupportTicket[]
}

const props = defineProps<Props>()
const query = defineModel<string>('query', { required: true })
const emit = defineEmits<{ contact: []; outage: [] }>()

const search = useTemplateRef<{ focus: () => void }>('search')
const shortcutHint = isMac() ? '⌘ ↵' : 'Ctrl ↵'

const contextChip = computed(() => {
	const server = getSupportServer(props.context)
	if (server) {
		return { icon: 'lucide-server', label: server.title || server.resource_id }
	}
	const site = typeof props.context.Site === 'string' ? props.context.Site : ''
	if (site) return { icon: 'lucide-globe', label: site }
	return null
})

function submitOnShortcut(event: KeyboardEvent): void {
	if (!(event.metaKey || event.ctrlKey) || event.key !== 'Enter') return
	event.preventDefault()
	if (props.action === 'contact') emit('contact')
}

function focus(): void {
	search.value?.focus()
}

onMounted(focus)

defineExpose({ focus })
</script>

<template>
	<div class="flex min-h-0 flex-1 flex-col">
		<div class="flex items-center gap-2">
			<SupportSearchInput
				ref="search"
				v-model="query"
				:placeholder="__('Describe what is going wrong')"
				:label="__('Describe what is going wrong')"
				@keydown="submitOnShortcut"
			/>
			<div
				v-if="contextChip"
				class="flex shrink-0 items-center gap-1.5 rounded-4 bg-surface-gray-2 px-2 py-1 text-sm text-ink-gray-7"
			>
				<span
					:class="[contextChip.icon, 'size-3.5 text-ink-gray-5']"
					aria-hidden="true"
				/>
				<span class="max-w-40 truncate">{{ contextChip.label }}</span>
			</div>
		</div>

		<div
			class="-mx-2 mt-2 min-h-0 flex-1 overflow-y-auto overscroll-contain py-2"
		>
			<SupportAnswers
				:query="query"
				:loading="loading"
				:error="error"
				:articles="articles"
				:tickets="tickets"
				:open-tickets="openTickets"
			/>
		</div>

		<div
			class="flex items-center justify-between gap-2 border-t border-outline-gray-2 pt-3"
		>
			<Button
				class="-ml-2"
				variant="ghost"
				icon-left="lucide-siren"
				:label="__('Report an outage')"
				@click="emit('outage')"
			/>
			<div class="flex items-center gap-2">
				<kbd
					v-if="action === 'contact'"
					class="inline-flex h-5 min-w-5 items-center justify-center rounded-1 border border-outline-gray-2 bg-surface-gray-2 px-1 font-sans text-p-xs text-ink-gray-5"
				>
					{{ shortcutHint }}
				</kbd>
				<Button
					:variant="action === 'contact' ? 'solid' : 'subtle'"
					:label="action === 'dismiss' ? __('Still need help?') : __('Contact support')"
					:disabled="action === 'disabled'"
					@click="emit('contact')"
				/>
			</div>
		</div>
	</div>
</template>
