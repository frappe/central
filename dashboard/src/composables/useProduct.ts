import { computed, reactive, watch } from 'vue'
import { useRoute } from 'vue-router'
import { API } from '@/api/methods'
import { getFrappe, methodUrl, queryString } from '@/lib/auth'
import type { Product } from '@/types/Signups/Product'

export type ProductBranding = Pick<Product, 'title' | 'logo' | 'subtitle'>

// Read once per product and shared by every page of the signup funnel.
const brandings = reactive(new Map<string, ProductBranding | null>())

/** The product a signup link names in `?product=`, and its branding once loaded. */
export function useProduct() {
	const route = useRoute()
	const productKey = computed(() => queryString(route.query.product))

	watch(productKey, load, { immediate: true })

	return {
		productKey,
		product: computed(() => brandings.get(productKey.value) ?? null),
	}
}

async function load(productKey: string) {
	if (!productKey || brandings.has(productKey)) return

	brandings.set(productKey, null)
	try {
		const branding = await getFrappe<ProductBranding | null>(
			methodUrl(API.getProduct),
			{ product: productKey },
		)
		brandings.set(productKey, branding)
	} catch {
		// Branding only decorates the pages. Creating the site reports a real refusal.
		brandings.delete(productKey)
	}
}
