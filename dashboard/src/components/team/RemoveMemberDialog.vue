<script setup lang="ts">
import { computed, ref } from 'vue'
import { Dialog } from 'frappe-ui'
import { useTeamMembers } from '@/composables/useTeamMembers'
import { useSession } from '@/composables/useSession'
import type { TeamMemberRow } from '@/types/api'

const props = defineProps<{ member: TeamMemberRow | null }>()
const emit = defineEmits<{ 'update:member': [member: TeamMemberRow | null] }>()

const { remove } = useTeamMembers()
const { activeTeamLabel } = useSession()

const open = computed({
	get: () => !!props.member,
	set: (v: boolean) => {
		if (!v) emit('update:member', null)
	},
})

const removing = ref(false)

const confirmRemove = async (): Promise<void> => {
	if (!props.member) return
	removing.value = true
	const ok = await remove(props.member.user)
	removing.value = false
	if (ok) open.value = false
}

const dialogOptions = computed(() => ({
	title: `Remove ${props.member?.full_name ?? ''}?`,
	actions: [
		{
			label: 'Cancel',
			variant: 'outline' as const,
			onClick: () => {
				open.value = false
			},
		},
		{
			label: 'Remove',
			variant: 'solid' as const,
			theme: 'red' as const,
			loading: removing.value,
			onClick: confirmRemove,
		},
	],
}))
</script>

<template>
	<Dialog v-model="open" :title="dialogOptions.title" size="sm" :actions="dialogOptions.actions">
		<p class="text-p-base text-ink-gray-7">
			They'll immediately lose access to
			<span class="font-semibold text-ink-gray-9">{{ activeTeamLabel }}'s</span>
			team and all its servers and sites. You can re-invite them at any time.
		</p>
	</Dialog>
</template>
