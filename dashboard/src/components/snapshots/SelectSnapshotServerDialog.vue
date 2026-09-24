<script setup lang="ts">
import { Alert, Button, Dialog, FormControl } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import type { VirtualMachineRow } from '@/composables/useServers'

interface Props {
	modelValue: boolean
	servers: VirtualMachineRow[]
	loading: boolean
	error: string | null
}

const props = defineProps<Props>()
const emit = defineEmits<{
	'update:modelValue': [value: boolean]
	selected: [server: VirtualMachineRow]
	retry: []
}>()
const router = useRouter()
const selectedName = ref('')
const open = computed({
	get: () => props.modelValue,
	set: (value: boolean) => emit('update:modelValue', value),
})
const options = computed(() => [
	{ label: 'Select a server', value: '' },
	...props.servers.map((server) => ({
		label: `${server.title || server.resource_id} · ${server.region}`,
		value: server.name,
	})),
])

watch(open, (value) => {
	if (value) selectedName.value = ''
})

function continueToSnapshot() {
	const server = props.servers.find((row) => row.name === selectedName.value)
	if (!server) return
	open.value = false
	emit('selected', server)
}

function viewServers() {
	open.value = false
	router.push('/servers')
}
</script>

<template>
	<Dialog v-model="open" title="Take a snapshot" size="sm">
		<div class="space-y-4">
			<p class="text-p-sm text-ink-gray-6">
				Choose the server whose disk you want to snapshot.
			</p>
			<p v-if="loading" class="text-p-sm text-ink-gray-5">Loading servers…</p>
			<Alert
				v-else-if="error"
				theme="red"
				title="Couldn't load servers"
				:description="error"
				:primary-action="{ label: 'Try again', onClick: () => emit('retry') }"
			/>
			<div v-else-if="!servers.length" class="space-y-3">
				<p class="text-p-sm text-ink-gray-6">
					No server is ready for a snapshot.
				</p>
				<Button label="View servers" variant="subtle" @click="viewServers" />
			</div>
			<template v-else>
				<FormControl
					v-model="selectedName"
					type="select"
					label="Server"
					:options="options"
				/>
				<div class="flex justify-end gap-2">
					<Button label="Cancel" @click="open = false" />
					<Button
						label="Continue"
						variant="solid"
						:disabled="!selectedName"
						@click="continueToSnapshot"
					/>
				</div>
			</template>
		</div>
	</Dialog>
</template>
