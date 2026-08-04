<script setup lang="ts">
import { Badge, Button, Spinner } from 'frappe-ui'
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import BillingCard from '@/components/billing/BillingCard.vue'
import { useServices } from '@/composables/useServices'

// Overview: plan + status, the models the plan grants, and which sites have AI on.
// Enabling is done on the server (bench) dashboard — the bench owns its site list —
// so Central shows what's enabled and links out. Usage lives in Billing.
const router = useRouter()
const { instance, instanceLoading } = useServices()

const planTitle = computed(
	() => instance.value?.plan_title || instance.value?.plan || '—',
)
const models = computed(() => instance.value?.models ?? [])
const enabledSites = computed(() => instance.value?.enabled_sites ?? [])
</script>

<template>
	<div class="min-h-0 flex-1 overflow-y-auto">
		<div class="mx-auto w-full max-w-3xl space-y-5 px-6 py-8">
			<div
				v-if="instanceLoading && !instance"
				class="flex justify-center py-16"
			>
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
						{{ enabledSites.length }}
						{{ enabledSites.length === 1 ? 'site' : 'sites' }}
						with AI enabled
					</p>
					<button
						class="mt-4 inline-flex items-center gap-1 text-p-sm font-medium text-ink-gray-7 hover:text-ink-gray-9"
						@click="router.push('/billing')"
					>
						View token usage in Billing
						<span class="lucide-arrow-up-right size-3.5" aria-hidden="true" />
					</button>
				</section>

				<BillingCard title="Sites with AI enabled">
					<ul v-if="enabledSites.length" class="divide-y divide-outline-gray-1">
						<li
							v-for="site in enabledSites"
							:key="site"
							class="flex items-center gap-2 py-2.5"
						>
							<span class="size-2 shrink-0 rounded-full bg-surface-green-3" />
							<span class="truncate text-sm text-ink-gray-8">{{ site }}</span>
						</li>
					</ul>
					<p v-else class="text-p-sm text-ink-gray-5">
						No sites have AI enabled yet. Enable it from a server's dashboard.
					</p>
					<div class="mt-4">
						<Button
							label="Manage on your servers"
							icon-right="lucide-arrow-up-right"
							variant="subtle"
							@click="router.push('/servers')"
						/>
					</div>
				</BillingCard>

				<BillingCard title="Included models">
					<ul v-if="models.length" class="divide-y divide-outline-gray-1">
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
