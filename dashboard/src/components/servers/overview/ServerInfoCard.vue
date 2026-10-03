<script setup lang="ts">
import CopyableValue from '@/components/common/CopyableValue.vue'
import ProviderAvatar from '@/components/servers/ProviderAvatar.vue'
import { formatSyncedAt } from '@/lib/format'

interface ServerInfoCardProps {
	hostedOn: string
	provider?: string | null
	plan: string
	publicIpv4?: string | null
	publicIpv6?: string | null
	isFirewallEnabled?: boolean
	isUbuntu?: boolean
	frappeVersion: string
	createdOn?: string | null
	ownedBy: string
}

defineProps<ServerInfoCardProps>()
</script>

<template>
	<section class="rounded-7 border border-outline-gray-2 p-5">
		<h3 class="mb-5 text-base font-semibold text-ink-gray-9">
			Server information
		</h3>
		<dl class="space-y-3.5 text-sm">
			<div class="flex items-center justify-between gap-4">
				<dt class="text-ink-gray-5">Hosted on</dt>
				<dd class="flex items-center gap-1.5 text-ink-gray-9">
					<ProviderAvatar :provider="provider" :size="16" />
					{{ hostedOn }}
				</dd>
			</div>
			<div class="flex items-center justify-between gap-4">
				<dt class="text-ink-gray-5">Plan</dt>
				<dd class="text-ink-gray-9">{{ plan }}</dd>
			</div>
			<div v-if="publicIpv6" class="flex items-center justify-between gap-4">
				<dt class="shrink-0 text-ink-gray-5">Public IPv6</dt>
				<dd class="min-w-0">
					<CopyableValue :value="publicIpv6" label="IPv6 address" />
				</dd>
			</div>
			<div v-if="publicIpv4" class="flex items-center justify-between gap-4">
				<dt class="shrink-0 text-ink-gray-5">Public IPv4</dt>
				<dd class="min-w-0">
					<CopyableValue :value="publicIpv4" label="IPv4 address" />
				</dd>
			</div>
			<div
				v-if="!publicIpv4 && !publicIpv6"
				class="flex items-center justify-between gap-4"
			>
				<dt class="text-ink-gray-5">Public address</dt>
				<dd class="text-ink-gray-9">None</dd>
			</div>
			<div class="flex items-center justify-between gap-4">
				<dt class="text-ink-gray-5">Firewall</dt>
				<dd class="text-ink-gray-9">{{ isFirewallEnabled ? 'On' : 'Off' }}</dd>
			</div>
			<div v-if="!isUbuntu" class="flex items-center justify-between gap-4">
				<dt class="text-ink-gray-5">Frappe version</dt>
				<dd class="text-ink-gray-9">{{ frappeVersion }}</dd>
			</div>
			<div class="flex items-center justify-between gap-4">
				<dt class="text-ink-gray-5">Created on</dt>
				<dd class="text-ink-gray-9">{{ formatSyncedAt(createdOn) || '-' }}</dd>
			</div>
			<div class="flex items-center justify-between gap-4">
				<dt class="text-ink-gray-5">Owned by</dt>
				<dd class="text-ink-gray-9">{{ ownedBy }}</dd>
			</div>
			<!-- Extra rows a caller owns, such as the server's snapshots. -->
			<slot />
		</dl>
	</section>
</template>
