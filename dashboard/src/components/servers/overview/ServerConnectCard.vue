<script setup lang="ts">
import { Button } from 'frappe-ui'
import CopyableValue from '@/components/common/CopyableValue.vue'

interface ServerConnectCardProps {
	sshCommand?: string | null
	canOpenConsole?: boolean
	/** Set when the console cannot open now, such as on a stopped server. */
	consoleUnavailableReason?: string | null
	openingConsole?: boolean
}

defineProps<ServerConnectCardProps>()
const emit = defineEmits<{ openConsole: [] }>()
</script>

<template>
	<section class="rounded-7 border border-outline-gray-2 p-5">
		<div class="flex items-start justify-between gap-4">
			<div>
				<h3 class="text-base font-semibold text-ink-gray-9">Connect</h3>
				<p class="mt-1 text-p-sm text-ink-gray-6">
					Open a shell in your browser, or use SSH with a key selected for this
					server.
				</p>
			</div>
			<Button
				v-if="canOpenConsole"
				variant="solid"
				label="Open web console"
				icon-left="lucide-terminal"
				class="shrink-0"
				:loading="openingConsole"
				:disabled="!!consoleUnavailableReason"
				@click="emit('openConsole')"
			/>
		</div>
		<p
			v-if="canOpenConsole && consoleUnavailableReason"
			class="mt-2 text-p-sm text-ink-gray-5"
		>
			{{ consoleUnavailableReason }}
		</p>

		<div class="mt-4">
			<p class="text-sm text-ink-gray-5">SSH command</p>
			<CopyableValue
				v-if="sshCommand"
				:value="sshCommand"
				label="SSH command"
				block
				class="mt-1.5"
			/>
			<p v-else class="mt-1.5 text-p-sm text-ink-gray-5">
				The SSH command appears when this server has a public address.
			</p>
			<p v-if="sshCommand" class="mt-2 text-p-sm text-ink-gray-5">
				If needed, add
				<code class="font-mono">-i /path/to/private_key</code>
				after <code class="font-mono">ssh</code>.
			</p>
		</div>
	</section>
</template>
