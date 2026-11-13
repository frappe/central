<script setup lang="ts">
import { Alert, Button, Textarea, useCall } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { API, method } from '@/api/methods'
import SupportTargetFields from '@/components/support/SupportTargetFields.vue'
import SupportTopicFields from '@/components/support/SupportTopicFields.vue'
import { useMyProfile } from '@/composables/useMyProfile'
import { useSession } from '@/composables/useSession'
import type {
	SupportCategoryKey,
	SupportCategoryOption,
	SupportContext,
	SupportServer,
	SupportTicket,
} from '@/composables/useSupport'
import { getSupportCategory } from '@/composables/useSupport'
import type { OutageIssue } from '@/composables/useSupportAnswers'
import { getErrorMessage, successToast } from '@/lib/feedback'
import { submitOrThrow } from '@/lib/frappeCall'
import { __ } from '@/lib/translate'

interface Props {
	context: SupportContext
	options: SupportCategoryOption[]
	optionsLoading: boolean
	optionsFinished: boolean
	optionsError: unknown
	askText: string
	preset: OutageIssue | null
}

interface CreateTicketParams {
	team: string
	category: string
	issue_type: string
	subject?: string
	description: string
	server?: string
	site?: string
}

const props = defineProps<Props>()
const emit = defineEmits<{
	created: []
	creating: [value: boolean]
	cancel: []
	retryOptions: []
}>()

const { activeTeam } = useSession()
const { profile } = useMyProfile()
const createCall = useCall<SupportTicket, CreateTicketParams>({
	url: method(API.createSupportTicket),
	method: 'POST',
	immediate: false,
})
const targets = ref<{ reset: () => void } | null>(null)

const category = ref<SupportCategoryKey | ''>('')
const issueType = ref('')
const serverId = ref('')
const siteName = ref('')
const description = ref('')
const formError = ref('')
const creating = ref(false)
const selection = ref<{ server: SupportServer | null; site: string }>({
	server: null,
	site: '',
})

const selectedCategory = computed(
	() => props.options.find((option) => option.key === category.value) ?? null,
)
const isCriticalIssue = computed(
	() =>
		selectedCategory.value?.issues.some(
			(issue) => issue.label === issueType.value && issue.is_critical,
		) ?? false,
)
const canSubmit = computed(
	() =>
		Boolean(category.value) &&
		Boolean(issueType.value) &&
		Boolean(description.value.trim()),
)
const sentLine = computed(() => {
	const server = selection.value.server
	const parts = [
		profile.value?.email,
		server?.title || server?.resource_id,
		server?.region,
	]
	return parts.filter(Boolean).join(' · ')
})

function resetForm(): void {
	const text = props.askText.trim()
	category.value =
		props.preset?.category ?? getSupportCategory(props.context) ?? ''
	issueType.value = props.preset?.issue ?? matchingIssue(props.context.Topic)
	targets.value?.reset()
	description.value = text
	formError.value = ''
}

function matchingIssue(topic: SupportContext[string]): string {
	if (typeof topic !== 'string' || !topic) return ''
	return (
		selectedCategory.value?.issues.find((c) => c.label === topic)?.label ?? ''
	)
}

async function submit(): Promise<void> {
	if (!canSubmit.value || creating.value) return

	creating.value = true
	formError.value = ''
	emit('creating', true)
	try {
		await submitOrThrow(createCall, {
			team: activeTeam.value!,
			category: category.value as string,
			issue_type: issueType.value,
			subject: props.askText.trim().slice(0, 140) || undefined,
			description: description.value.trim(),
			server: serverId.value || undefined,
			site: siteName.value || undefined,
		})
		successToast(__('Support ticket created'))
		resetForm()
		emit('created')
	} catch (error) {
		formError.value = getErrorMessage(error, "The ticket couldn't be created.")
	} finally {
		creating.value = false
		emit('creating', false)
	}
}

// The issue belongs to a category, so a switch drops one that no longer fits.
watch(category, () => {
	if (
		!props.options.length ||
		!issueType.value ||
		selectedCategory.value?.issues.some((i) => i.label === issueType.value)
	)
		return
	issueType.value = ''
})

// The catalog loads after the dialog opens, so a topic from the context matches when it lands.
watch(
	() => props.options,
	() => {
		if (!issueType.value) issueType.value = matchingIssue(props.context.Topic)
	},
)

// The ask text, the context, or the catalog can land after mount or change while the dialog stays open.
watch(
	[() => props.askText, () => props.preset, () => props.context],
	resetForm,
	{ immediate: true },
)
</script>

<template>
	<form class="flex min-h-0 flex-1 flex-col" @submit.prevent="submit">
		<div
			class="-mx-1 flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto overscroll-contain px-1 pb-3"
		>
			<SupportTopicFields
				v-model:category="category"
				v-model:issue-type="issueType"
				:options="props.options"
				:loading="props.optionsLoading"
				:finished="props.optionsFinished"
				:error="props.optionsError"
				@retry-options="emit('retryOptions')"
			/>

			<SupportTargetFields
				ref="targets"
				v-model:server-id="serverId"
				v-model:site-name="siteName"
				:context="props.context"
				:category="category"
				@selection="selection = $event"
			/>

			<Textarea
				v-model="description"
				:rows="4"
				:label="__('Details for support')"
				:placeholder="__('What were you doing, what did you expect, and what error did you see?')"
				required
			/>

			<Alert
				v-if="isCriticalIssue"
				theme="amber"
				:title="__('This is urgent, so support sees it first.')"
			/>

			<p v-if="sentLine" class="text-p-sm text-ink-gray-5">
				{{ __('Sent as {0}', [sentLine]) }}
			</p>

			<Alert v-if="formError" theme="red" :title="formError" />
		</div>

		<div
			class="flex items-center justify-between gap-2 border-t border-outline-gray-2 pt-3"
		>
			<Button
				class="-ml-2"
				variant="ghost"
				:label="__('Cancel')"
				:disabled="creating"
				@click="emit('cancel')"
			/>
			<Button
				type="submit"
				variant="solid"
				:label="__('Send to support')"
				:loading="creating"
				:disabled="!canSubmit"
			/>
		</div>
	</form>
</template>
