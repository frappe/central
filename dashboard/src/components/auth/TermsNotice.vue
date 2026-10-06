<script setup lang="ts">
const POLICIES_URL = 'https://frappe.io/cloud/policies'
</script>

<template>
	<p class="text-center text-p-sm text-ink-gray-5">
		By continuing, you agree to our
		<a
			class="font-medium text-ink-gray-8 hover:underline"
			:href="POLICIES_URL"
			target="_blank"
			rel="noopener noreferrer"
		>
			Terms and Policies</a
		>
	</p>
</template>
