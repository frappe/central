<script setup lang="ts">
import { Alert, Avatar, LoadingText } from 'frappe-ui'
import { computed, onMounted, ref } from 'vue'
import {
	addPartner,
	findPartner,
	usePartnerLinkIntent,
} from '@/composables/usePartnerLinks'
import { useSession } from '@/composables/useSession'
import { getErrorMessage } from '@/lib/feedback'
import { __ } from '@/lib/translate'
import type { PartnerPreview } from '@/types/api'

defineEmits<{ submit: [] }>()

const session = useSession()
const intent = usePartnerLinkIntent()
const partner = ref<PartnerPreview | null>(null)
const loading = ref(true)
const saving = ref(false)
const error = ref('')

onMounted(async () => {
	try {
		partner.value = await findPartner(
			session.activeTeam.value!,
			intent.code.value,
		)
	} catch (failure) {
		error.value = getErrorMessage(failure, "We couldn't find this partner.")
	} finally {
		loading.value = false
	}
})

async function submit(): Promise<boolean> {
	saving.value = true
	error.value = ''
	try {
		await addPartner(
			session.activeTeam.value!,
			intent.code.value,
			intent.reference.value,
		)
		await session.reload()
		intent.clear()
		return true
	} catch (failure) {
		error.value = getErrorMessage(failure, "We couldn't add the partner.")
		return false
	} finally {
		saving.value = false
	}
}

defineExpose({
	canSubmit: computed(() => Boolean(partner.value) && !saving.value),
	submitLabel: computed(() =>
		partner.value
			? __('Add {0}', [partner.value.partner_name])
			: __('Add partner'),
	),
	saving,
	submit,
})

const addPartnerErrorTitle = __("Couldn't add the partner")
</script>

<template>
	<div class="space-y-4">
		<Alert
			v-if="error"
			theme="red"
			:title="addPartnerErrorTitle"
			:description="error"
		/>
		<LoadingText v-if="loading" :text="__('Loading partner')" />
		<div
			v-else-if="partner"
			class="flex items-center gap-3 rounded-6 border border-outline-gray-2 p-4"
		>
			<Avatar
				:image="partner.partner_logo ?? undefined"
				:label="partner.partner_name"
				size="2xl"
				shape="square"
			/>
			<div class="min-w-0">
				<p class="truncate text-base-medium text-ink-gray-9">
					{{ partner.partner_name }}
				</p>
				<p class="mt-0.5 text-p-sm text-ink-gray-5">
					{{ __('Partner code {0}', [intent.code.value]) }}
				</p>
			</div>
		</div>
	</div>
</template>
