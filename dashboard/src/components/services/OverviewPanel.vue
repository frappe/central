<script setup lang="ts">
import { useRouter } from 'vue-router'
import { Badge } from 'frappe-ui'
import { useServices } from '@/composables/useServices'

// The Overview tab: plan, entitlement status, and the models the plan grants.
// Usage details (tokens this period, spend) will land here later — it reads off the
// same billing meter, linked out for now.
const router = useRouter()
const { instance } = useServices()
</script>

<template>
	<div class="min-h-0 flex-1 overflow-y-auto px-4 py-5 sm:px-6">
		<div class="mx-auto max-w-3xl space-y-6">
			<section class="rounded-lg border border-outline-gray-2 bg-surface-elevation-1 p-5">
				<div class="flex items-start justify-between gap-3">
					<div>
						<h2 class="text-base font-semibold text-ink-gray-9">Plan</h2>
						<p class="mt-1 text-p-sm text-ink-gray-5">
							{{ instance?.plan_title || instance?.plan || '—' }}
						</p>
					</div>
					<Badge
						:label="instance?.status ?? 'Active'"
						:theme="instance?.status === 'Active' ? 'green' : 'orange'"
						variant="subtle"
					/>
				</div>

				<div class="mt-4">
					<p class="mb-2 text-p-sm font-medium text-ink-gray-7">Included models</p>
					<div v-if="instance?.models.length" class="flex flex-wrap gap-2">
						<Badge
							v-for="m in instance.models"
							:key="m.name"
							:label="`${m.name} · ${m.tier}`"
							theme="gray"
							variant="subtle"
						/>
					</div>
					<p v-else class="text-p-sm text-ink-gray-5">
						No models yet - they appear once your plan grants a tier and the provider
						has published models.
					</p>
				</div>

				<button
					class="mt-4 inline-flex items-center gap-1 text-p-sm font-medium text-ink-gray-7 hover:text-ink-gray-9"
					@click="router.push('/billing')"
				>
					View token usage in Billing
					<span class="lucide-arrow-up-right size-3.5" />
				</button>
			</section>
		</div>
	</div>
</template>
