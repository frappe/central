<script setup lang="ts">
import { useColorScheme } from 'frappe-ui'
import ErrorBoundary from '@/components/common/ErrorBoundary.vue'

useColorScheme()
</script>

<template>
	<ErrorBoundary>
		<router-view />
	</ErrorBoundary>
</template>
