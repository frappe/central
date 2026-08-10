<script setup lang="ts">
import { Dialog, FormControl } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { useSession } from '@/composables/useSession'
import { useTeamMembers } from '@/composables/useTeamMembers'
import { useTeamSettings } from '@/composables/useTeamSettings'
import type { TeamMemberRow } from '@/types/api'

// Transfer ownership — the one action an owner can't undo alone: afterwards only
// the new owner can hand it back. So it asks for the member's name to be typed,
// the same bar a destructive delete gets.
const props = defineProps<{ member: TeamMemberRow | null }>()
const emit = defineEmits<{ 'update:member': [member: TeamMemberRow | null] }>()

const { transferOwnership, saving } = useTeamSettings()
const { reload } = useTeamMembers()
const { activeTeamLabel } = useSession()

const open = computed({
	get: () => !!props.member,
	set: (v: boolean) => {
		if (!v) emit('update:member', null)
	},
})

const typed = ref('')
watch(open, () => (typed.value = ''))

const expected = computed(() => props.member?.full_name ?? '')
const confirmed = computed(
	() => typed.value.trim().toLowerCase() === expected.value.trim().toLowerCase(),
)

async function confirm(): Promise<void> {
	if (!props.member || !confirmed.value) return
	if (await transferOwnership(props.member.user)) {
		reload()
		open.value = false
	}
}

const dialogOptions = computed(() => ({
	title: 'Transfer ownership',
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
		:title="dialogOptions.title"
		size="sm"
		:actions="dialogOptions.actions"
	>
		<div class="space-y-4">
			<p class="text-p-base text-ink-gray-7">
				<span class="font-medium text-ink-gray-9">{{ expected }}</span> becomes
				the owner of
				<span class="font-medium text-ink-gray-9">{{ activeTeamLabel }}</span>
				and you drop to Admin. Only the new owner can hand it back.
			</p>
			<FormControl
				v-model="typed"
				label="Type the member's name to confirm"
				:placeholder="expected"
				autocomplete="off"
			/>
		</div>
	</Dialog>
</template>
