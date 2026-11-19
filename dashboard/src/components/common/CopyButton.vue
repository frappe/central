<script setup lang="ts">
import { Button } from 'frappe-ui'
import { ref } from 'vue'
import { copyToClipboard } from '@/lib/clipboard'
import { reportError } from '@/lib/feedback'

interface Props {
	text: string
}

const props = defineProps<Props>()

const copied = ref(false)

const copy = async (): Promise<void> => {
	if (!(await copyToClipboard(props.text))) {
		reportError('Could not copy. Select the text and copy it manually.')

		return
	}

	copied.value = true

	setTimeout(() => {
		copied.value = false
	}, 1000)
}
</script>

<template>
	<Button
		variant="ghost"
		:icon="copied ? 'lucide-check' : 'lucide-copy'"
		label="Copy"
		@click="copy"
	/>
</template>
