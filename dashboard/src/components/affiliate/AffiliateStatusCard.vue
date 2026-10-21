<script setup lang="ts">
import { Alert, Button } from 'frappe-ui'
import { computed } from 'vue'
import { getErrorMessage } from '@/lib/feedback'
import type { AffiliateStatus } from '@/types/affiliates'

interface AffiliateStatusCardProps {
	/** Null when the user never applied. */
	status: Exclude<AffiliateStatus, 'Active'> | null
	rejectionReason: string | null
	applying: boolean
	applyError: unknown
}

const props = defineProps<AffiliateStatusCardProps>()
defineEmits<{ apply: [] }>()

const content = computed(() => {
	switch (props.status) {
		case 'Pending':
			return {
				icon: 'lucide-hourglass',
				title: 'Your request is under review',
				description:
					'We will review your request soon. This page shows your affiliate link when we approve it.',
				action: null,
			}
		case 'Rejected':
			return {
				icon: 'lucide-circle-x',
				title: 'Your request was not approved',
				description: null,
				action: 'Request again',
			}
		case 'Disabled':
			return {
				icon: 'lucide-circle-pause',
				title: 'Your affiliate account is paused',
				description:
					'Your link does not count new visits or signups. Contact support if you have questions.',
				action: null,
			}
		default:
			return {
				icon: 'lucide-megaphone',
				title: 'Earn by sharing Frappe Cloud',
				description:
					'Share a link to Frappe Cloud or a Frappe product. See how many people visit, sign up and become paying customers.',
				action: 'Become an affiliate',
			}
	}
})
</script>

<template>
	<section
		aria-labelledby="affiliate-status-heading"
		class="flex flex-col items-start gap-4 rounded-6 border border-outline-gray-1 bg-surface-base p-5"
	>
		<div
			class="flex size-10 items-center justify-center rounded-6 bg-surface-gray-2 text-ink-gray-6"
		>
			<span :class="[content.icon, 'size-4']" aria-hidden="true" />
		</div>
		<div class="flex flex-col gap-1">
			<h2
				id="affiliate-status-heading"
				class="text-base-semibold text-ink-gray-8"
			>
				{{ content.title }}
			</h2>
			<p v-if="content.description" class="max-w-xl text-p-sm text-ink-gray-5">
				{{ content.description }}
			</p>
			<p
				v-if="status === 'Rejected' && rejectionReason"
				class="max-w-xl whitespace-pre-line text-p-sm text-ink-gray-7"
			>
				Reason: {{ rejectionReason }}
			</p>
		</div>
		<Alert
			v-if="applyError"
			theme="red"
			title="Couldn't send your request"
			:description="getErrorMessage(applyError)"
		/>
		<Button
			v-if="content.action"
			variant="solid"
			:label="content.action"
			:loading="applying"
			@click="$emit('apply')"
		/>
	</section>
</template>
