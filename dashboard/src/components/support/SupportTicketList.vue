<script setup lang="ts">
import { Badge, Button, Skeleton } from 'frappe-ui'
import { computed, ref } from 'vue'
import EmptyState from '@/components/common/EmptyState.vue'
import SupportSearchInput from '@/components/support/SupportSearchInput.vue'
import type { SupportTicket } from '@/composables/useSupport'
import { timeAgo } from '@/lib/datetime'
import { getErrorMessage } from '@/lib/feedback'

interface Props {
	tickets: SupportTicket[] | null
	loading: boolean
	error: unknown
}

const props = defineProps<Props>()
const emit = defineEmits<{ retry: []; create: [] }>()

const filter = ref('')
const tickets = computed(() => props.tickets ?? [])
const rows = computed(() => {
	const query = filter.value.trim().toLowerCase()
	if (!query) return tickets.value

	return tickets.value.filter(
		(ticket) =>
			ticket.subject.toLowerCase().includes(query) ||
			ticket.name.toLowerCase().includes(query),
	)
})
</script>

<template>
	<div class="flex min-h-0 flex-1 flex-col">
		<div v-if="tickets.length" class="pb-3">
			<SupportSearchInput
				v-model="filter"
				placeholder="Search your tickets"
				label="Search your tickets"
			/>
		</div>

		<div class="-mx-2 min-h-0 flex-1 overflow-y-auto overscroll-contain">
			<div v-if="loading && !tickets" class="space-y-2 px-2" aria-busy="true">
				<Skeleton v-for="index in 3" :key="index" class="h-12 rounded-4" />
			</div>

			<EmptyState
				v-else-if="error"
				icon="lucide-cloud-off"
				title="Tickets couldn't load"
				:description="getErrorMessage(error, 'Try again in a moment.')"
			>
				<template #action>
					<Button label="Retry" @click="emit('retry')" />
				</template>
			</EmptyState>

			<EmptyState
				v-else-if="!tickets.length"
				icon="lucide-life-buoy"
				title="No tickets yet"
				description="Ask a question in Get help. A ticket appears here after you send it."
			>
				<template #action>
					<Button variant="solid" label="Get help" @click="emit('create')" />
				</template>
			</EmptyState>

			<ul v-else-if="rows.length" class="space-y-0.5">
				<li v-for="ticket in rows" :key="ticket.name">
					<component
						:is="ticket.url ? 'a' : 'div'"
						:href="ticket.url || undefined"
						:target="ticket.url ? '_blank' : undefined"
						:rel="ticket.url ? 'noopener noreferrer' : undefined"
						class="flex w-full items-center gap-2 rounded-4 p-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-outline-gray-4"
						:class="ticket.url ? 'hover:bg-surface-gray-2' : ''"
					>
						<span
							class="lucide-ticket size-4 shrink-0 text-ink-gray-6"
							aria-hidden="true"
						/>
						<span class="min-w-0 flex-1">
							<span class="block truncate text-sm text-ink-gray-8">
								{{ ticket.subject }}
							</span>
							<span class="block text-p-xs text-ink-gray-5">
								#{{ ticket.name }}
								<template v-if="ticket.creation">
									· {{ timeAgo(ticket.creation) }}</template
								>
								<template v-if="!ticket.url && ticket.raised_by">
									· Raised by {{ ticket.raised_by }}</template
								>
							</span>
						</span>
						<Badge
							theme="blue"
							variant="subtle"
							size="sm"
							:label="ticket.status"
						/>
						<span
							v-if="ticket.url"
							class="lucide-arrow-up-right size-3.5 shrink-0 text-ink-gray-5"
							aria-hidden="true"
						/>
					</component>
				</li>
			</ul>

			<p v-else class="px-2 py-6 text-center text-p-sm text-ink-gray-5">
				No tickets match "{{ filter.trim() }}".
			</p>
		</div>
	</div>
</template>
