<script setup lang="ts">
import ErrorBoundary from "@/components/common/ErrorBoundary.vue";
</script>

<template>
	<ErrorBoundary>
		<router-view />
	</ErrorBoundary>
</template>
