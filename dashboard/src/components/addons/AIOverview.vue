<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { Badge, Button, Spinner, useCall } from 'frappe-ui'
import { API, method } from '@/api/methods'
import { useServices } from '@/composables/useServices'
import { useSession } from '@/composables/useSession'
import { whenTeamReady } from '@/composables/useTeamScope'

interface MeteredRow {
	resource_type: string | null
	settlement_mode: string
	period_usage: number
}

const router = useRouter()
const { instance, instanceLoading } = useServices()
const { activeTeam } = useSession()

const metered = useCall<{ services: MeteredRow[] }, { team: string }>({
	url: method(API.meteredServices),
	params: () => ({ team: activeTeam.value! }),
	immediate: false,
	refetch: true,
})

whenTeamReady(() => metered.reload())

const tokenRow = computed(() =>
	metered.data?.services.find((s) => s.resource_type === 'Tokens'),
)

const tokensThisCycle = computed(() => {
	const tokens = tokenRow.value?.period_usage

	if (!tokens) return '0'

	return new Intl.NumberFormat(undefined, {
		notation: 'compact',
		maximumFractionDigits: 1,
	}).format(tokens)
})

const settlementLine = computed(() => {
	const mode = tokenRow.value?.settlement_mode
	if (mode === 'Prepaid Pack') return 'Prepaid pack · capped at your bundle'

	return 'Postpaid overage · billed per token'
})

const planTitle = computed(
	() => instance.value?.plan_title || instance.value?.plan || '—',
)
const models = computed(() => instance.value?.models ?? [])
const enabledSites = computed(() => instance.value?.enabled_sites ?? [])
</script>

<template>
	<div class="min-h-0 flex-1 overflow-y-auto">
		<div class="mx-auto w-full max-w-3xl px-6 pb-8 pt-5">
			<div
				v-if="instanceLoading && !instance"
				class="flex justify-center py-16"
			>
				<Spinner class="size-5 text-ink-gray-5" />
			</div>

			<!-- plan card -->
			<template v-else>
				<section
					class="rounded-lg border border-outline-gray-2 bg-surface-base p-5"
				>
					<div class="flex h-6 items-center justify-between gap-3">
						<span class="text-p-sm text-ink-gray-5">Plan</span>
						<Badge
							:label="instance?.status ?? 'Active'"
							:theme="instance?.status === 'Active' ? 'green' : 'orange'"
							variant="subtle"
						/>
					</div>

					<div class="mt-1.5 flex items-end justify-between gap-4">
						<div class="min-w-0">
							<p class="truncate text-sm font-semibold text-ink-gray-9">
								{{ planTitle }}
							</p>
							<p class="mt-1 text-p-sm text-ink-gray-5">{{ settlementLine }}</p>
						</div>

						<div class="shrink-0 text-right">
							<div class="text-lg font-semibold tabular-nums text-ink-gray-9">
								{{ tokensThisCycle }}
							</div>
							<div class="text-p-xs text-ink-gray-5">tokens this cycle</div>
						</div>
					</div>
				</section>

				<h2 class="text-base font-semibold text-ink-gray-8 mt-8">
					Sites with AI enabled

					<span v-if="enabledSites.length" class="font-normal text-ink-gray-5">
						· {{ enabledSites.length }}
					</span>
				</h2>

				<ul
					v-if="enabledSites.length"
					class="mt-3 divide-y divide-outline-gray-1 border-t border-outline-gray-1"
				>
					<li
						v-for="site in enabledSites"
						:key="site.site"
						class="flex items-center gap-2.5 py-2.5"
					>
						<span class="size-2 shrink-0 rounded-full bg-surface-green-4" />
						<span class="min-w-0 flex-1 truncate text-sm text-ink-gray-8">
							{{ site.site }}
						</span>

						<span
							v-if="site.cluster"
							class="shrink-0 text-p-xs text-ink-gray-5"
						>
							{{ site.cluster }}
						</span>
					</li>
				</ul>

				<p v-else class="mt-1 text-p-sm text-ink-gray-5">
					No sites have AI enabled yet. Enable it from a server's dashboard.
				</p>

				<Button
					class="-ml-2 mt-3"
					variant="ghost"
					size="sm"
					label="Manage on your servers"
					icon-right="lucide-arrow-up-right"
					@click="router.push('/servers')"
				/>

				<h2
					class="text-base font-semibold text-ink-gray-8 mt-8 border-t border-outline-gray-2 pt-8"
				>
					Included models
				</h2>

				<p class="mt-0.5 text-p-sm text-ink-gray-5">
					Granted by your plan's tiers.
				</p>

				<table v-if="models.length" class="mt-3 w-full border-collapse">
					<tbody class="divide-y divide-outline-gray-1">
						<tr v-for="model in models" :key="model.name">
							<td
								class="py-3 pr-3 font-mono text-sm font-medium text-ink-gray-9"
							>
								{{ model.name }}
							</td>

							<td class="py-3 text-right text-p-sm text-ink-gray-5">
								{{ model.tier }}
							</td>
						</tr>
					</tbody>
				</table>

				<p v-else class="mt-3 text-p-sm text-ink-gray-5">
					No models yet. They appear once your plan grants a tier and the
					provider publishes them.
				</p>
			</template>
		</div>
	</div>
</template>
