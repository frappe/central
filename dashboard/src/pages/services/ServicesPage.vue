<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { Badge, Spinner } from 'frappe-ui'
import PageHeader from '@/components/common/PageHeader.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import { useServices } from '@/composables/useServices'
import type { ServiceOffer } from '@/composables/useServices'

// The add-on catalogue. One card per active service (LLM hosting today); the
// backend list is generic, so future services surface here with no page change.
// A card links into its detail page whether or not it's activated — activation is
// the first action there.

const router = useRouter()
const { offers, offersLoading } = useServices()

// Presentation for known services; anything else falls back to a neutral default
// so a newly-added backend service still renders sensibly.
const META: Record<string, { icon: string; description: string }> = {
	llm: {
		icon: 'lucide-sparkles',
		description:
			'Managed LLM inference for your sites. Enable it per site, or use the key in your own apps.',
	},
}

function metaFor(name: string) {
	return META[name] ?? { icon: 'lucide-box', description: 'Managed add-on service.' }
}

const cards = computed(() =>
	offers.value.map((offer: ServiceOffer) => ({
		...offer,
		...metaFor(offer.name),
		activated: !!offer.managed_service,
	})),
)

function openService(name: string): void {
	router.push(`/services/${name}`)
}
</script>

<template>
	<div class="flex h-full flex-col">
		<PageHeader title="Services" />

		<div class="min-h-0 flex-1 overflow-y-auto px-4 py-6 sm:px-6">
			<div v-if="offersLoading && !offers.length" class="flex justify-center py-16">
				<Spinner class="size-5 text-ink-gray-5" />
			</div>

			<EmptyState
				v-else-if="!offers.length"
				icon="lucide-box"
				title="No services available"
				description="There are no add-on services offered for your team yet."
			/>

			<div v-else class="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
				<button
					v-for="card in cards"
					:key="card.name"
					class="group flex flex-col rounded-lg border border-outline-gray-2 bg-surface-elevation-1 p-5 text-left transition-shadow hover:shadow-md"
					@click="openService(card.name)"
				>
					<div class="flex items-start justify-between gap-3">
						<div
							class="flex size-10 items-center justify-center rounded-lg bg-surface-gray-2 text-ink-gray-7"
						>
							<span :class="[card.icon, 'size-5']" aria-hidden="true" />
						</div>
						<Badge
							:label="card.activated ? 'Active' : 'Not enabled'"
							:theme="card.activated ? 'green' : 'gray'"
							variant="subtle"
							size="sm"
						/>
					</div>
					<h2 class="mt-4 text-base font-semibold text-ink-gray-9">
						{{ card.title }}
					</h2>
					<p class="mt-1 flex-1 text-p-sm text-ink-gray-5">
						{{ card.description }}
					</p>
					<span
						class="mt-4 inline-flex items-center gap-1 text-p-sm font-medium text-ink-gray-7 group-hover:text-ink-gray-9"
					>
						{{ card.activated ? 'Manage' : 'Set up' }}
						<span class="lucide-arrow-right size-3.5" />
					</span>
				</button>
			</div>
		</div>
	</div>
</template>
