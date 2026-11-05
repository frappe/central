<script setup lang="ts">
interface AirportProps {
	/** The IATA airport code that names the region, such as `BOM`. */
	code: string
}

defineProps<AirportProps>()
</script>

<template>
	<span class="docs-airport">{{ code.toUpperCase() }}</span>
</template>
