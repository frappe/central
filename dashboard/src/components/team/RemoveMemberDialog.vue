<script setup lang="ts">
import { Dialog } from 'frappe-ui'
import { computed, ref } from 'vue'
import { useSession } from '@/composables/useSession'
import { useTeamMembers } from '@/composables/useTeamMembers'
import type { TeamMemberRow } from '@/types/api'

interface Props {
	member: TeamMemberRow | null
}

const props = defineProps<Props>()
const open = defineModel<boolean>('open', { default: false })

const { remove } = useTeamMembers()
const { activeTeamLabel } = useSession()

const removing = ref(false)

const confirmRemove = async (): Promise<void> => {
	if (!props.member) return
	removing.value = true
	const ok = await remove(props.member.user)
	removing.value = false
	if (ok) open.value = false
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
	<Dialog
		v-model="open"
		:title="`Remove ${member?.full_name}?`"
		size="sm"
		:actions="dialogOptions.actions"
	>
		<p class="text-p-base text-ink-gray-7">
			They'll immediately lose access to
			<span class="font-semibold text-ink-gray-9">{{ activeTeamLabel }}'s</span>
			team and all its servers and sites. You can re-invite them at any time.
		</p>
	</Dialog>
</template>
