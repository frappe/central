<script setup lang="ts">
import { ErrorMessage } from 'frappe-ui'
import ContactSupportLink from '@/components/common/ContactSupportLink.vue'
import { type SupportContext, useSupport } from '@/composables/useSupport'

interface Props {
	message: string
	/** The auth page, such as "Sign in". The ticket names only the page, never the email. */
	page: string
	/** More for the ticket subject, such as the product or a reference. */
	context?: SupportContext
}

defineProps<Props>()

const hasSupport = !!useSupport().getTicketUrl()
</script>

<template>
	<div class="space-y-1">
		<ErrorMessage :message="message" />
		<p v-if="hasSupport" class="text-p-sm text-ink-gray-6">
			Still stuck?
			<ContactSupportLink :context="{ Page: page, ...context }"
				>Contact support</ContactSupportLink
			>.
		</p>
	</div>
</template>
