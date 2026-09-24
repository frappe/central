<script setup lang="ts">
import { Button } from 'frappe-ui'
import ProviderAvatar from '@/components/servers/ProviderAvatar.vue'
import { copyToClipboard } from '@/lib/clipboard'
import { reportError, successToast } from '@/lib/feedback'
import { formatSyncedAt } from '@/lib/format'

const props = defineProps<{
	hostedOn: string
	provider?: string | null
	plan: string
	inboundIp: string
	isUbuntu?: boolean
	sshCommand?: string | null
	frappeVersion: string
	createdOn?: string | null
	ownedBy: string
}>()

async function copySshCommand(): Promise<void> {
	if (!props.sshCommand) return
	if (await copyToClipboard(props.sshCommand)) {
		successToast('SSH command copied')
		return
	}
	reportError('Could not copy the SSH command. Select it and copy it manually.')
}
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
				<dt class="text-ink-gray-5">Public IPv4</dt>
				<dd class="font-mono text-ink-gray-9">{{ inboundIp }}</dd>
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
		<div v-if="isUbuntu" class="mt-5 border-t border-outline-gray-2 pt-5">
			<h4 class="text-sm font-medium text-ink-gray-9">Connect with SSH</h4>
			<p class="mt-1 text-p-sm text-ink-gray-6">
				Run this in your terminal with the private key that matches a key
				selected for this server. If needed, add
				<code class="font-mono">-i /path/to/private_key</code>
				after ssh.
			</p>
			<div v-if="sshCommand" class="mt-3 flex items-center gap-2">
				<code
					class="min-w-0 flex-1 select-all overflow-x-auto rounded-4 bg-surface-gray-2 px-3 py-2 font-mono text-p-sm text-ink-gray-9"
					>{{ sshCommand }}</code
				>
				<Button
					label="Copy command"
					icon-left="lucide-copy"
					@click="copySshCommand"
				/>
			</div>
			<p v-else class="mt-3 text-p-sm text-ink-gray-5">
				The SSH command will appear when this server has a public IPv4 address.
			</p>
		</div>
	</section>
</template>
