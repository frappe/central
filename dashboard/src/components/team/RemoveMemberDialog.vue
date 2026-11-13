<script setup lang="ts">
import { Alert, Dialog } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import TranslatedText from '@/components/common/TranslatedText.vue'
import { useSession } from '@/composables/useSession'
import { useTeamMembers } from '@/composables/useTeamMembers'
import { getErrorMessage } from '@/lib/feedback'
import { __ } from '@/lib/translate'
import type { TeamMemberRow } from '@/types/api'

interface Props {
	member: TeamMemberRow | null
}

const props = defineProps<Props>()
const open = defineModel<boolean>('open', { default: false })

const { remove } = useTeamMembers()
const { activeTeamLabel } = useSession()

const removing = ref(false)
const formError = ref('')
watch(
	() => props.member,
	() => (formError.value = ''),
)

const confirmRemove = async (): Promise<void> => {
	if (!props.member) return
	removing.value = true
	formError.value = ''
	try {
		await remove(props.member.user, { throwOnError: true })
		open.value = false
	} catch (e) {
		formError.value = getErrorMessage(e, "The member couldn't be removed.")
	} finally {
		removing.value = false
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
			label: __('Remove'),
			variant: 'solid' as const,
			theme: 'red' as const,
			onClick: confirmRemove,
		},
	],
}))
</script>

<template>
	<Dialog
		v-model="open"
		:title="__('Remove {0}?', [member?.full_name])"
		size="sm"
		:actions="dialogOptions.actions"
	>
		<div class="space-y-4">
			<Alert
				v-if="formError"
				theme="red"
				:title="__('Couldn\'t remove the member')"
				:description="formError"
			/>
			<p class="text-p-base text-ink-gray-7">
				<TranslatedText
					:text="__('They\'ll immediately lose access to {0} team and all its servers and sites. You can re-invite them at any time.')"
				>
					<template #0>
						<span class="text-p-base-semibold text-ink-gray-9"
							>{{ __("{0}'s", [activeTeamLabel]) }}</span
						>
					</template>
				</TranslatedText>
			</p>
		</div>
	</Dialog>
</template>
