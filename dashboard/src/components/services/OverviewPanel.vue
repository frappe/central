<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { Badge, Spinner } from 'frappe-ui'
import BillingCard from '@/components/billing/BillingCard.vue'
import { useServices } from '@/composables/useServices'

// Overview: plan + status at a glance, then the models the plan grants. Same card
// language as Billing Overview — summary surfaces sit in bordered cards, not flush
// like the Sites/API Keys list tabs. Usage lives in Billing, linked from here.
const router = useRouter()
const { instance, instanceLoading, sites } = useServices()

const planTitle = computed(
	() => instance.value?.plan_title || instance.value?.plan || '—',
)
const models = computed(() => instance.value?.models ?? [])
const enabledCount = computed(() => instance.value?.enabled_sites.length ?? 0)
</script>

<template>
	<div class="min-h-0 flex-1 overflow-y-auto">
		<div class="mx-auto w-full max-w-3xl space-y-5 px-6 py-8">
			<div v-if="instanceLoading && !instance" class="flex justify-center py-16">
				<Spinner class="size-5 text-ink-gray-5" />
			</div>

			<template v-else>
				<section
					class="rounded-xl border border-outline-gray-2 bg-surface-elevation-1 p-5"
				>
					<div class="flex h-6 items-center justify-between gap-3">
						<span class="text-p-sm text-ink-gray-5">Plan</span>
						<Badge
							:label="instance?.status ?? 'Active'"
							:theme="instance?.status === 'Active' ? 'green' : 'orange'"
							variant="subtle"
						/>
					</div>
					<p class="mt-1.5 truncate text-2xl font-semibold text-ink-gray-9">
						{{ planTitle }}
					</p>
					<p class="mt-1.5 text-p-sm text-ink-gray-5">
						{{ enabledCount }} of {{ sites.length }}
						{{ sites.length === 1 ? 'site' : 'sites' }} with AI enabled
					</p>
					<button
						class="mt-4 inline-flex items-center gap-1 text-p-sm font-medium text-ink-gray-7 hover:text-ink-gray-9"
						@click="router.push('/billing')"
					>
						View token usage in Billing
						<span class="lucide-arrow-up-right size-3.5" aria-hidden="true" />
					</button>
				</section>

				<BillingCard title="Included models">
					<ul
						v-if="models.length"
						class="divide-y divide-outline-gray-1"
					>
						<li
							v-for="model in models"
							:key="model.name"
							class="flex items-center justify-between gap-3 py-3"
						>
							<span class="truncate text-sm font-medium text-ink-gray-8">
								{{ model.name }}
							</span>
							<span class="shrink-0 text-p-sm text-ink-gray-5">
								{{ model.tier }}
							</span>
						</li>
					</ul>
					<p v-else class="text-p-sm text-ink-gray-5">
						No models yet. They appear once your plan grants a tier and the
						provider publishes them.
					</p>
				</BillingCard>
			</template>
		</div>
	</div>
</template>
