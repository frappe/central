<script setup lang="ts">
import { Textarea } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import { endPartnerLink } from '@/composables/usePartnerLinks'
import { getErrorMessage } from '@/lib/feedback'
import { __ } from '@/lib/translate'
import type { PartnerLink } from '@/types/api'

interface EndPartnerLinkDialogProps {
	/** The name of the team on the other side of the link. */
	otherTeamName: string
}

const props = defineProps<EndPartnerLinkDialogProps>()
const emit = defineEmits<{ ended: [link: PartnerLink] }>()
const target = defineModel<PartnerLink | null>('target', { default: null })

const reason = ref('')
const ending = ref(false)
const error = ref('')

watch(target, () => {
	reason.value = ''
	error.value = ''
})

const message = computed(() =>
	__(
		'The link with {0} ends now. To work together again, the customer adds the partner again.',
		[props.otherTeamName],
	),
)

async function confirm(link: PartnerLink): Promise<void> {
	if (!reason.value.trim()) {
		error.value = __('Enter the reason for ending the link.')
		return
	}
	ending.value = true
	error.value = ''
	try {
		const ended = await endPartnerLink(link.name, reason.value.trim())
		target.value = null
		emit('ended', ended)
	} catch (failure) {
		error.value = getErrorMessage(failure, "We couldn't end the link.")
	} finally {
		ending.value = false
	}
}
</script>

<template>
	<ConfirmDialog
		v-model:target="target"
		:title="__('End partner link')"
		:message="message"
		:confirm-label="__('End link')"
		theme="red"
		:confirm-text="otherTeamName"
		:loading="ending"
		:error="error"
		@confirm="confirm"
	>
		<Textarea
			v-model="reason"
			class="mt-4"
			:label="__('Reason')"
			:placeholder="__('The other team reads this.')"
			:rows="3"
		/>
	</ConfirmDialog>
</template>
