<script setup lang="ts">
import { Badge, Button, Spinner } from 'frappe-ui'
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { useServices } from '@/composables/useServices'

const router = useRouter()
const { instance, instanceLoading } = useServices()

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

			<!-- status card: LLM hosting has no billing plan -->
			<template v-else>
				<section
					class="rounded-6 border border-outline-gray-2 bg-surface-base p-5"
				>
					<div class="flex h-6 items-center justify-between gap-3">
						<span class="text-p-sm text-ink-gray-5">Status</span>
						<Badge
							:label="instance?.status ?? 'Active'"
							:theme="instance?.status === 'Active' ? 'green' : 'amber'"
						/>
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
					The models your keys can call.
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
								{{ model.modality }}
							</td>
						</tr>
					</tbody>
				</table>

				<p v-else class="mt-3 text-p-sm text-ink-gray-5">
					No models accessible yet.
				</p>
			</template>
		</div>
	</div>
</template>
