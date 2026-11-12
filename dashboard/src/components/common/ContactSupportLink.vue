<script setup lang="ts">
import { computed } from 'vue'
import { type SupportContext, useSupport } from '@/composables/useSupport'

interface Props {
	/** What the ticket is about. It becomes the ticket subject. */
	context?: SupportContext
}

const props = withDefaults(defineProps<Props>(), { context: () => ({}) })

const { canUseInAppTickets, getTicketUrl, openSupport } = useSupport()
const ticketUrl = computed(() => getTicketUrl(props.context))
</script>

<!-- Without support the words stay as plain text, so the sentence still reads. -->
<template>
	<button
		v-if="canUseInAppTickets"
		type="button"
		class="text-ink-gray-8 underline underline-offset-2 hover:text-ink-gray-9"
		@click="openSupport(props.context)"
	>
		<slot>contact support</slot>
	</button>
	<a
		v-else-if="ticketUrl"
		:href="ticketUrl"
		target="_blank"
		rel="noopener noreferrer"
		class="text-ink-gray-8 underline underline-offset-2 hover:text-ink-gray-9"
		><slot>contact support</slot></a
	>
	<span v-else><slot>contact support</slot></span>
</template>
