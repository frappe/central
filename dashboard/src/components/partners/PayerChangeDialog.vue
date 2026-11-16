<script setup lang="ts">
import { ref, watch } from 'vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import { setPartnerPayer } from '@/composables/usePartnerLinks'
import { getErrorMessage } from '@/lib/feedback'
import type { PartnerLink, PartnerPayer } from '@/types/api'

/** One change of who pays, with the words the person confirms. */
export interface PayerChange {
	link: string
	payer: PartnerPayer
	title: string
	message: string
	confirmLabel: string
	isDestructive?: boolean
}

const emit = defineEmits<{ changed: [link: PartnerLink] }>()
const target = defineModel<PayerChange | null>('target', { default: null })

const saving = ref(false)
const error = ref('')

watch(target, () => {
	error.value = ''
})

async function confirm(change: PayerChange): Promise<void> {
	saving.value = true
	error.value = ''
	try {
		const link = await setPartnerPayer(change.link, change.payer)
		target.value = null
		emit('changed', link)
	} catch (failure) {
		error.value = getErrorMessage(failure, "We couldn't change who pays.")
	} finally {
		saving.value = false
	}
}
</script>

<template>
	<ConfirmDialog
		v-model:target="target"
		:title="target?.title ?? ''"
		:message="target?.message"
		:confirm-label="target?.confirmLabel"
		:theme="target?.isDestructive ? 'red' : undefined"
		:loading="saving"
		:error="error"
		@confirm="confirm"
	/>
</template>
