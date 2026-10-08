<script setup lang="ts">
import { useProduct } from '@/composables/useProduct'

const { product } = useProduct()
</script>

<template>
	<img
		v-if="product?.logo"
		:src="product.logo"
		:alt="product.title"
		class="size-8 shrink-0 object-contain"
	/>
</template>
