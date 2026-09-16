<script setup lang="ts">
import { Dialog, TextInput } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { useSession } from '@/composables/useSession'
import { useTeamMembers } from '@/composables/useTeamMembers'
import { useTeamSettings } from '@/composables/useTeamSettings'
import type { TeamMemberRow } from '@/types/api'

interface Props {
	member: TeamMemberRow | null
}

const props = defineProps<Props>()
const open = defineModel<boolean>('open', { default: false })

const { transferOwnership, saving } = useTeamSettings()
const { reload } = useTeamMembers()
const { activeTeamLabel } = useSession()

const typed = ref('')
watch(open, (isOpen) => {
	if (isOpen) typed.value = ''
})

const expected = computed(() => props.member?.full_name ?? '')
const confirmed = computed(
	() =>
		typed.value.trim().toLowerCase() === expected.value.trim().toLowerCase(),
)

const confirm = async (): Promise<void> => {
	if (!props.member || !confirmed.value) return
	if (await transferOwnership(props.member.user)) {
		reload()
		open.value = false
	}
}

const dialogOptions = computed(() => ({
	actions: [
		{
			label: 'Cancel',
			variant: 'outline' as const,
			onClick: () => {
				open.value = false
			},
		},
		{
			label: 'Transfer ownership',
			variant: 'solid' as const,
			theme: 'red' as const,
			loading: saving.value,
			disabled: !confirmed.value,
			onClick: confirm,
		},
	],
}))
</script>

<template>
	<Dialog
		v-model="open"
		title="Transfer ownership"
		size="sm"
		:actions="dialogOptions.actions"
	>
		<div class="space-y-4">
			<p class="text-p-base text-ink-gray-7">
				<span class="font-medium text-ink-gray-9">{{ expected }}</span>
				becomes the owner of
				<span class="font-medium text-ink-gray-9">{{ activeTeamLabel }}</span>
				and you drop to Admin. Only the new owner can hand it back.
			</p>
			<TextInput
				v-model="typed"
				label="Type the member's name to confirm"
				:placeholder="expected"
				autocomplete="off"
			/>
		</div>
	</Dialog>
</template>
