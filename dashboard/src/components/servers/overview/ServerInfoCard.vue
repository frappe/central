<script setup lang="ts">
import ProviderAvatar from '@/components/servers/ProviderAvatar.vue'
import { formatSyncedAt } from '@/lib/format'

defineProps<{
	hostedOn: string
	provider?: string | null
	plan: string
	inboundIp: string
	frappeVersion: string
	createdOn?: string | null
	ownedBy: string
}>()
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
			<div class="flex items-center justify-between gap-4">
				<dt class="text-ink-gray-5">Inbound IP</dt>
				<dd class="font-mono text-ink-gray-9">{{ inboundIp }}</dd>
			</div>
			<div class="flex items-center justify-between gap-4">
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
		</dl>
	</section>
</template>
