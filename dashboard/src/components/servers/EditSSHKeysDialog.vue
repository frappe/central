<script setup lang="ts">
import { Alert, Dialog, useCall } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { API, method } from '@/api/methods'
import SSHKeysField from '@/components/servers/SSHKeysField.vue'
import { useSession } from '@/composables/useSession'
import { getErrorMessage } from '@/lib/feedback'
import type { ServerSSHKey } from '@/types/servers'

interface Props {
	resourceId: string
	keys: ServerSSHKey[]
}

const props = defineProps<Props>()
const open = defineModel<boolean>('open', { default: false })
const emit = defineEmits<{ saved: [] }>()

const { activeTeam } = useSession()
const selected = ref<string[]>([])

const keysCall = useCall<
	null,
	{ team: string; resource_id: string; ssh_keys: string[] }
>({
	url: method(API.setServerSSHKeys),
	method: 'POST',
	immediate: false,
})

watch(open, (isOpen) => {
	if (!isOpen) return

	selected.value = props.keys.map((key) => key.name)
	keysCall.reset()
})

const isChanged = computed(
	() => selected.value.join() !== props.keys.map((key) => key.name).join(),
)

const error = computed(() =>
	keysCall.error
		? getErrorMessage(keysCall.error, "Couldn't change the SSH keys.")
		: '',
)

async function save(): Promise<void> {
	if (!isChanged.value || !activeTeam.value) return

	await keysCall.submit({
		team: activeTeam.value,
		resource_id: props.resourceId,
		ssh_keys: selected.value,
	})
	if (keysCall.error) return

	open.value = false
	emit('saved')
}
</script>

<template>
	<Dialog
		v-model="open"
		title="Edit SSH keys"
		:actions="[
			{
				label: 'Save',
				variant: 'solid',
				disabled: !isChanged,
				loading: keysCall.loading,
				onClick: save,
			},
		]"
	>
		<template #default>
			<div class="space-y-4">
				<Alert v-if="error" theme="red" :title="error" />

				<SSHKeysField v-model="selected" />

				<p class="text-p-sm text-ink-gray-5">
					{{ selected.length
							? 'The change applies at the next sign-in. Open sessions stay connected.'
							: 'With no key, only the web console in Actions can sign in.' }}
				</p>
			</div>
		</template>
	</Dialog>
</template>
