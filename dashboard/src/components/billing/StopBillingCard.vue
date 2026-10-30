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
	<section
		aria-labelledby="suspend-heading"
		class="flex flex-wrap items-center gap-4 rounded-6 border border-outline-red-2 px-5 py-4"
	>
		<div class="min-w-0 flex-[1_1_20rem]">
			<h2 id="suspend-heading" class="text-base-semibold text-ink-gray-8">
				Stop all servers
			</h2>
			<p class="mt-0.5 text-p-sm text-ink-gray-5">
				<template v-if="running.length">
					Stops {{ serverCount }}. Sites will be unavailable. Data is retained,
					and you can restart the servers.
				</template>
				<template v-else>No servers are running.</template>
			</p>
		</div>
		<Button
			v-if="canPowerServer"
			theme="red"
			label="Stop all"
			:disabled="!running.length"
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
				Sites on these servers will be unavailable until you restart them. Data,
				snapshots, and configuration are retained.
			</p>
		</ConfirmDialog>
	</section>
</template>
