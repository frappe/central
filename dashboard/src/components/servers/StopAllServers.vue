<script setup lang="ts">
import { Button } from 'frappe-ui'
import { computed, ref } from 'vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import { useCapabilities } from '@/composables/useCapabilities'
import { useServerMapData } from '@/composables/useServerMapData'
import { useServers } from '@/composables/useServers'
import { useSession } from '@/composables/useSession'
import { getErrorMessage, successToast } from '@/lib/feedback'
import { plural } from '@/lib/format'

const { canPowerServer } = useCapabilities()
const { activeTeamLabel } = useSession()
const { servers } = useServerMapData()
const { runCommand } = useServers()

const running = computed(() =>
	servers.value.filter(
		(server) =>
			server.status === 'Running' &&
			(server.capabilities?.includes('server:power') ?? canPowerServer.value),
	),
)

const serverCount = computed(() => plural(running.value.length, 'server'))

// The servers to stop while the confirmation is open; null closes it.
const stopTarget = ref<typeof running.value | null>(null)
const error = ref('')
const suspending = ref(false)

const openConfirmation = (): void => {
	error.value = ''
	stopTarget.value = running.value
}

const suspendAll = async () => {
	suspending.value = true
	error.value = ''

	const results = await Promise.allSettled(
		running.value.map((server) =>
			runCommand('stop', server, { throwOnError: true }),
		),
	)

	suspending.value = false

	const failed = results.filter((result) => result.status === 'rejected')

	if (failed.length) {
		error.value = getErrorMessage(
			(failed[0] as PromiseRejectedResult).reason,
			`${plural(failed.length, 'server')} could not be stopped.`,
		)

		return
	}

	stopTarget.value = null
	successToast(`Stop requested for ${serverCount.value}`)
}
</script>

<template>
	<Button
		v-if="canPowerServer && running.length"
		theme="red"
		icon-left="lucide-power"
		label="Stop all"
		@click="openConfirmation"
	/>

	<ConfirmDialog
		v-model:target="stopTarget"
		:title="`Stop ${running.length === 1 ? 'your server' : `all ${serverCount}`}?`"
		confirm-label="Stop servers"
		theme="red"
		:loading="suspending"
		:error="error"
		:confirm-text="activeTeamLabel"
		@confirm="suspendAll"
	>
		<p class="text-p-base text-ink-gray-6">
			Stops {{ serverCount }}. Sites on these servers will be unavailable until
			you restart them. Data, snapshots, and configuration are retained.
		</p>
	</ConfirmDialog>
</template>
