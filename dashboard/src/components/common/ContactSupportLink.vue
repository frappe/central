<script setup lang="ts">
import { computed } from 'vue'
import { type SupportContext, useSupport } from '@/composables/useSupport'

interface Props {
	/** What the ticket is about. It becomes the ticket subject. */
	context?: SupportContext
}

const props = withDefaults(defineProps<Props>(), { context: () => ({}) })

const { getTicketUrl } = useSupport()
const ticketUrl = computed(() => getTicketUrl(props.context))
</script>

<!-- Without a support URL the words stay as plain text, so the sentence still reads. -->
<template>
	<a
		v-if="ticketUrl"
		:href="ticketUrl"
		target="_blank"
		rel="noopener noreferrer"
		class="text-ink-gray-8 underline underline-offset-2 hover:text-ink-gray-9"
		><slot>contact support</slot></a
	>
	<span v-else><slot>contact support</slot></span>
</template>
