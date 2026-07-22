<script setup lang="ts">
import { computed, ref } from 'vue'
import { Badge, Button, Spinner, Switch } from 'frappe-ui'
import ConnectionDetailsDialog from '@/components/services/ConnectionDetailsDialog.vue'
import DisableSiteDialog from '@/components/services/DisableSiteDialog.vue'
import { useServices } from '@/composables/useServices'
import type { ServiceModel } from '@/composables/useServices'

// The Sites tab: turn AI on/off per site (the switch), and reveal a site's key +
// curl once it's on. Enabled state is derived from the instance's enabled_sites.
const props = defineProps<{
	managedService: string
	models: ServiceModel[]
	canManage: boolean
}>()

const { sites, instance, instanceLoading, busySite, enableSite, disableSite } = useServices()

const enabledSites = computed(() => new Set(instance.value?.enabled_sites ?? []))
const rows = computed(() =>
	sites.value.map((site) => ({
		...site,
		enabled: enabledSites.value.has(site.name),
	})),
)

// Turning on provisions immediately (safe); turning off confirms first (cuts a key).
const connectSite = ref<string | null>(null)
const pendingDisable = ref<string | null>(null)

function toggleSite(site: string, enabled: boolean): void {
	if (enabled) enableSite(props.managedService, site)
	else pendingDisable.value = site
}

async function confirmDisable(site: string): Promise<void> {
	pendingDisable.value = null
	await disableSite(props.managedService, site)
}
</script>

<template>
	<div class="min-h-0 flex-1 overflow-y-auto px-4 py-5 sm:px-6">
		<section class="mx-auto max-w-3xl">
			<div class="flex items-center justify-between gap-3">
				<div>
					<h2 class="text-base font-semibold text-ink-gray-9">Your sites</h2>
					<p class="mt-1 text-p-sm text-ink-gray-5">
						Enable AI on a site and it works out of the box. Reveal the key to use it
						from your own apps.
					</p>
				</div>
				<Spinner v-if="instanceLoading" class="size-4 text-ink-gray-4" />
			</div>

			<div v-if="!sites.length" class="mt-4 py-10 text-center text-p-sm text-ink-gray-5">
				No sites in this team yet.
			</div>

			<ul v-else class="mt-4 divide-y divide-outline-gray-1">
				<li v-for="row in rows" :key="row.name" class="flex items-center gap-3 py-3">
					<span
						class="size-2 shrink-0 rounded-full"
						:class="row.enabled ? 'bg-surface-green-3' : 'bg-surface-gray-4'"
					/>
					<div class="min-w-0 flex-1">
						<p class="truncate text-sm font-medium text-ink-gray-8">
							{{ row.name }}
						</p>
						<p class="truncate text-xs text-ink-gray-5">
							{{ row.enabled ? 'AI enabled' : 'Not enabled' }}
						</p>
					</div>

					<Button
						v-if="row.enabled && canManage"
						label="Connect"
						icon-left="lucide-terminal"
						variant="subtle"
						@click="connectSite = row.name"
					/>
					<Spinner v-if="busySite === row.name" class="size-4 text-ink-gray-4" />
					<Switch
						v-if="canManage"
						:model-value="row.enabled"
						:disabled="busySite === row.name"
						@update:model-value="(v: boolean) => toggleSite(row.name, v)"
					/>
					<Badge
						v-else-if="row.enabled"
						label="Enabled"
						theme="green"
						variant="subtle"
					/>
				</li>
			</ul>
		</section>
	</div>

	<ConnectionDetailsDialog
		v-if="connectSite"
		:open="!!connectSite"
		:managed-service="managedService"
		:site="connectSite"
		:models="models"
		@update:open="
			(v: boolean) => {
				if (!v) connectSite = null
			}
		"
	/>

	<DisableSiteDialog
		v-model:site="pendingDisable"
		:loading="busySite === pendingDisable"
		@confirm="confirmDisable"
	/>
</template>
