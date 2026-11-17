<script setup lang="ts">
import { computed } from 'vue'

interface Props {
	/** A translated sentence. Each `{0}`, `{1}` is filled by the slot of that name. */
	text: string
}

const props = defineProps<Props>()

// Splitting on a capture group keeps the placeholder numbers at the odd indexes.
const parts = computed(() =>
	props.text.split(/\{(\d+)\}/).map((part, index) => ({
		slot: index % 2 === 1 ? part : null,
		text: part,
	})),
)
</script>

<!-- Lets a sentence keep markup, such as a bold name, inside one translated string. -->
<template>
	<template v-for="(part, index) in parts" :key="index">
		<slot v-if="part.slot" :name="part.slot" />
		<template v-else>{{ part.text }}</template>
	</template>
</template>
