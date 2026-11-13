<script setup lang="ts">
import { Alert, Dialog, TextInput } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import TranslatedText from '@/components/common/TranslatedText.vue'
import { useSession } from '@/composables/useSession'
import { useTeamMembers } from '@/composables/useTeamMembers'
import { useTeamSettings } from '@/composables/useTeamSettings'
import { __ } from '@/lib/translate'
import type { TeamMemberRow } from '@/types/api'

interface Props {
	member: TeamMemberRow | null
}

const props = defineProps<Props>()
const open = defineModel<boolean>('open', { default: false })

const { transferOwnership, error, clearError } = useTeamSettings()
const { reload } = useTeamMembers()
const { activeTeamLabel } = useSession()

const typed = ref('')
watch(open, (isOpen) => {
	if (isOpen) typed.value = ''
	clearError()
})
watch(typed, clearError)

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
			label: __('Cancel'),
			variant: 'outline' as const,
			onClick: () => {
				open.value = false
			},
		},
		{
			label: __('Transfer ownership'),
			variant: 'solid' as const,
			theme: 'red' as const,
			disabled: !confirmed.value,
			onClick: confirm,
		},
	],
}))
</script>

<template>
	<Dialog
		v-model="open"
		:title="__('Transfer ownership')"
		size="sm"
		:actions="dialogOptions.actions"
	>
		<div class="space-y-4">
			<Alert
				v-if="error"
				theme="red"
				:title="__('Couldn\'t transfer ownership')"
				:description="error"
			/>
			<p class="text-p-base text-ink-gray-7">
				<TranslatedText
					:text="__('{0} becomes the owner of {1} and you drop to Admin. Only the new owner can hand it back.')"
				>
					<template #0>
						<span class="text-p-base-medium text-ink-gray-9"
							>{{ expected }}</span
						>
					</template>
					<template #1>
						<span class="text-p-base-medium text-ink-gray-9"
							>{{ activeTeamLabel }}</span
						>
					</template>
				</TranslatedText>
			</p>
			<TextInput
				v-model="typed"
				autofocus
				:label="__('Type the member\'s name to confirm')"
				:placeholder="expected"
				autocomplete="off"
			/>
		</div>
	</Dialog>
</template>
