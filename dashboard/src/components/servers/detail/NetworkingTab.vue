<script setup lang="ts">
import { Badge, Button } from 'frappe-ui'
import { computed } from 'vue'
import CopyButton from '@/components/common/CopyButton.vue'
import SettingsSection from '@/components/common/SettingsSection.vue'
import { useServerHostnames } from '@/composables/useServerHostnames'
import type { VirtualMachineRow } from '@/composables/useServers'
import type { ServerOverview } from '@/types/servers'

interface Props {
	server: VirtualMachineRow
	overview: ServerOverview
}

const props = defineProps<Props>()

const { hostnames, loading, error } = useServerHostnames(
	computed(() => props.server),
)

const addresses = computed(() =>
	[
		{ label: 'Public IPv6', value: props.overview.server.public_ipv6 },
		{ label: 'Public IPv4', value: props.overview.server.public_ipv4 },
		{ label: 'Private IPv6', value: props.overview.server.ipv6_address },
	].filter((row): row is { label: string; value: string } => !!row.value),
)

const isFirewallEnabled = computed(
	() => !!props.overview.server.is_firewall_enabled,
)

const firewallNote = computed(() =>
	isFirewallEnabled.value
		? 'Only SSH, HTTP and HTTPS can reach this server from the internet.'
		: 'Every port is open to the internet. Turn the firewall on when you create a server to allow only SSH, HTTP and HTTPS.',
)
</script>

<template>
	<div class="divide-y divide-outline-gray-1">
		<SettingsSection
			title="Addresses"
			help="Public addresses reach the server from the internet. The private address only works inside the region."
		>
			<dl v-if="addresses.length" class="space-y-1">
				<div
					v-for="row in addresses"
					:key="row.label"
					class="flex items-center gap-3"
				>
					<dt class="w-24 shrink-0 text-sm text-ink-gray-5">{{ row.label }}</dt>

					<dd class="min-w-0 truncate font-mono text-sm text-ink-gray-8">
						{{ row.value }}
					</dd>

					<CopyButton :text="row.value" />
				</div>
			</dl>

			<p v-else class="text-p-sm text-ink-gray-5">
				This server has no address yet. It gets one when it finishes setting up.
			</p>
		</SettingsSection>

		<SettingsSection title="Firewall">
			<template #actions>
				<Badge
					:label="isFirewallEnabled ? 'On' : 'Off'"
					:theme="isFirewallEnabled ? 'green' : 'gray'"
				/>
			</template>

			<p class="text-p-sm text-ink-gray-6">{{ firewallNote }}</p>
		</SettingsSection>

		<SettingsSection
			title="Domains"
			help="The site and custom domains this server answers. They stop working if the server is terminated."
		>
			<div v-if="loading" class="space-y-2" aria-busy="true">
				<div class="h-9 animate-pulse rounded-4 bg-surface-gray-2" />
				<div class="h-9 w-2/3 animate-pulse rounded-4 bg-surface-gray-2" />
			</div>

			<p v-else-if="error" class="text-p-sm text-ink-gray-5">{{ error }}</p>

			<p v-else-if="!hostnames.length" class="text-p-sm text-ink-gray-5">
				No site or custom domain points to this server.
			</p>

			<ul v-else class="divide-y divide-outline-gray-1">
				<li
					v-for="entry in hostnames"
					:key="entry.hostname"
					class="flex items-center gap-3 py-2 first:pt-0 last:pb-0"
				>
					<span
						class="lucide-globe size-4 shrink-0 text-ink-gray-5"
						aria-hidden="true"
					/>

					<span class="min-w-0 flex-1 truncate text-sm text-ink-gray-8">
						{{ entry.hostname }}
					</span>

					<Badge :label="entry.kind" />

					<Button
						variant="ghost"
						icon="lucide-arrow-up-right"
						:label="`Open ${entry.hostname}`"
						tooltip="Open"
						:link="`https://${entry.hostname}`"
					/>
				</li>
			</ul>
		</SettingsSection>
	</div>
</template>
