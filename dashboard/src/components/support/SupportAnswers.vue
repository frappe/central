<script setup lang="ts">
import { Badge, Skeleton } from 'frappe-ui'
import { computed } from 'vue'
import type {
	SupportArticle,
	SupportRelatedTicket,
	SupportTicket,
} from '@/composables/useSupport'
import { highlightWords } from '@/composables/useSupportAnswers'

interface Props {
	query: string
	loading: boolean
	error: boolean
	articles: SupportArticle[]
	tickets: SupportRelatedTicket[]
	openTickets: SupportTicket[]
}

const props = defineProps<Props>()

const hasQuery = computed(() => props.query.trim().length >= 3)
const hasResults = computed(
	() => props.articles.length > 0 || props.tickets.length > 0,
)
const recentTickets = computed(() => props.openTickets.slice(0, 3))
</script>

<template>
	<div v-if="!hasQuery" class="space-y-2">
		<p v-if="!recentTickets.length" class="text-p-sm text-ink-gray-5">
			Type to search help articles and your team's past tickets.
		</p>
		<template v-else>
			<p class="px-2 py-1 text-xs uppercase text-ink-gray-4">
				Your open tickets
			</p>
			<component
				:is="ticket.url ? 'a' : 'div'"
				v-for="ticket in recentTickets"
				:key="ticket.name"
				:href="ticket.url || undefined"
				:target="ticket.url ? '_blank' : undefined"
				:rel="ticket.url ? 'noopener noreferrer' : undefined"
				class="mb-0.5 flex w-full items-center gap-2 rounded-4 p-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-outline-gray-4"
				:class="ticket.url ? 'hover:bg-surface-gray-2' : ''"
			>
				<span
					class="lucide-ticket size-4 shrink-0 text-ink-gray-6"
					aria-hidden="true"
				/>
				<span class="min-w-0 flex-1 truncate text-sm text-ink-gray-8">
					{{ ticket.subject }}
				</span>
				<Badge theme="blue" variant="subtle" size="sm" :label="ticket.status" />
				<span
					v-if="ticket.url"
					class="lucide-arrow-up-right size-3.5 shrink-0 text-ink-gray-5"
					aria-hidden="true"
				/>
			</component>
		</template>
	</div>

	<div v-else-if="loading" class="space-y-2" aria-busy="true">
		<Skeleton v-for="index in 3" :key="index" class="h-12 rounded-4" />
	</div>

	<p v-else-if="error" class="text-p-sm text-ink-gray-5">
		Search is not available right now.
	</p>

	<p
		v-else-if="!hasResults"
		class="grid h-full place-items-center text-p-sm text-ink-gray-5"
	>
		No answers for "{{ query.trim() }}"
	</p>

	<div v-else class="space-y-3">
		<div v-if="articles.length">
			<p class="px-2 py-1 text-xs uppercase text-ink-gray-4">Help articles</p>
			<a
				v-for="article in articles"
				:key="article.name"
				:href="article.url"
				target="_blank"
				rel="noopener noreferrer"
				class="mb-0.5 flex w-full items-start gap-2 rounded-4 p-2 hover:bg-surface-gray-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-outline-gray-4"
			>
				<span
					class="lucide-book-open mt-0.5 size-4 shrink-0 text-ink-gray-6"
					aria-hidden="true"
				/>
				<span class="min-w-0 flex-1">
					<span
						class="block truncate text-sm text-ink-gray-8"
						v-html="highlightWords(article.title, query)"
					/>
					<span
						v-if="article.category || article.excerpt"
						class="mt-0.5 block truncate text-p-sm text-ink-gray-5"
					>
						<template v-if="article.category"
							>{{ article.category }}
							<template v-if="article.excerpt"> · </template></template
						><span v-html="highlightWords(article.excerpt, query)" />
					</span>
				</span>
				<span
					class="lucide-arrow-up-right mt-0.5 size-3.5 shrink-0 text-ink-gray-5"
					aria-hidden="true"
				/>
			</a>
		</div>

		<div v-if="tickets.length">
			<p class="px-2 py-1 text-xs uppercase text-ink-gray-4">
				Your team's tickets
			</p>
			<component
				:is="ticket.url ? 'a' : 'div'"
				v-for="ticket in tickets"
				:key="ticket.name"
				:href="ticket.url || undefined"
				:target="ticket.url ? '_blank' : undefined"
				:rel="ticket.url ? 'noopener noreferrer' : undefined"
				class="mb-0.5 flex w-full items-center gap-2 rounded-4 p-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-outline-gray-4"
				:class="ticket.url ? 'hover:bg-surface-gray-2' : ''"
			>
				<span
					class="lucide-ticket size-4 shrink-0 text-ink-gray-6"
					aria-hidden="true"
				/>
				<span class="min-w-0 flex-1">
					<span
						class="block truncate text-sm text-ink-gray-8"
						v-html="highlightWords(ticket.subject, query)"
					/>
					<span
						v-if="!ticket.url && ticket.raised_by"
						class="block truncate text-p-xs text-ink-gray-5"
					>
						Raised by {{ ticket.raised_by }}
					</span>
				</span>
				<Badge
					v-if="ticket.status"
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
		</div>
	</div>
</template>

<style scoped>
:deep(mark) {
	background-color: var(--surface-gray-3);
	color: var(--ink-gray-9);
	font-weight: 500;
}
</style>
