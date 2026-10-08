<script setup lang="ts">
import { Button } from 'frappe-ui'
import { ref } from 'vue'

interface Props {
	text: string
}

const props = defineProps<Props>()

const copied = ref(false)

const copy = async (): Promise<void> => {
	await navigator.clipboard.writeText(props.text)

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
