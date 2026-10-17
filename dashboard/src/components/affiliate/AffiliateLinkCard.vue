<script setup lang="ts">
import { Alert, Button, Select, TextInput } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { AFFILIATE_SOURCES, affiliateUrl } from '@/composables/useAffiliate'
import { copyToClipboard } from '@/lib/clipboard'
import { getErrorMessage, reportError, successToast } from '@/lib/feedback'
import type { LinkProduct, NewAffiliateLink } from '@/types/affiliates'

interface AffiliateLinkCardProps {
	code: string
	products: LinkProduct[]
	create: (link: NewAffiliateLink) => Promise<string>
}

const props = defineProps<AffiliateLinkCardProps>()

// "fc" is the reserved key for Frappe Cloud itself, so it never clashes with a product.
const FRAPPE_CLOUD = 'fc'

const slug = ref('')
const product = ref(FRAPPE_CLOUD)
const source = ref(AFFILIATE_SOURCES[0].value)
const campaign = ref('')
const copying = ref(false)
const createError = ref('')
// A saved slug fixes its choices, so a later change needs a new slug.
const savedLink = ref('')

const productOptions = computed(() => [
	{ label: 'Frappe Cloud', value: FRAPPE_CLOUD },
	...props.products.map(({ name, title }) => ({ label: title, value: name })),
])
const cleanSlug = computed(() => slug.value.trim().toLowerCase())
const cleanCampaign = computed(() => campaign.value.trim())

// A slug replaces only the code. The query carries the product, source and campaign.
const link = computed(() => {
	const base = affiliateUrl(cleanSlug.value || props.code)
	if (!cleanCampaign.value && product.value === FRAPPE_CLOUD) return base

	const query = new URLSearchParams()
	if (product.value !== FRAPPE_CLOUD) query.set('product', product.value)
	query.set('utm_source', source.value)
	if (cleanCampaign.value) query.set('utm_campaign', cleanCampaign.value)
	return `${base}?${query}`
})
const isSaved = computed(
	() => !cleanSlug.value || link.value === savedLink.value,
)

watch(link, () => {
	createError.value = ''
})

/** Save a new slug first, so the copied link credits the affiliate. */
async function copyLink(): Promise<void> {
	copying.value = true
	try {
		if (!isSaved.value) {
			await props.create(getNewLink())
			savedLink.value = link.value
		}
	} catch (error) {
		createError.value = getErrorMessage(error, "The link couldn't be saved.")
		return
	} finally {
		copying.value = false
	}

	if (await copyToClipboard(link.value)) successToast('Affiliate link copied')
	else reportError('Could not copy the link. Select it and copy it manually.')
}

function getNewLink(): NewAffiliateLink {
	return {
		slug: cleanSlug.value,
		product: product.value === FRAPPE_CLOUD ? '' : product.value,
		utm_source: source.value,
		utm_campaign: cleanCampaign.value,
	}
}
</script>

<template>
	<section
		aria-labelledby="affiliate-link-heading"
		class="flex min-w-0 flex-col gap-5 rounded-6 border border-outline-gray-1 bg-surface-base p-5"
	>
		<div class="flex flex-col gap-2">
			<h2
				id="affiliate-link-heading"
				class="text-base-semibold text-ink-gray-8"
			>
				Your link
			</h2>
			<div class="flex items-center gap-2">
				<p
					class="min-w-0 flex-1 break-all rounded-4 bg-surface-gray-2 px-3 py-2 font-mono text-p-sm text-ink-gray-7"
				>
					{{ link }}
				</p>
				<Button
					variant="ghost"
					icon="lucide-copy"
					label="Copy link"
					:loading="copying"
					@click="copyLink"
				/>
			</div>
		</div>

		<div class="flex flex-col gap-3 border-t border-outline-gray-1 pt-5">
			<TextInput
				v-model="campaign"
				label="Campaign"
				placeholder="erpnext v16"
				maxlength="140"
			/>
			<div class="grid grid-cols-2 gap-3">
				<Select v-model="product" :options="productOptions" label="Product" />
				<Select v-model="source" :options="AFFILIATE_SOURCES" label="Source" />
			</div>
			<TextInput
				v-model="slug"
				label="Link slug (optional)"
				placeholder="bwh"
				maxlength="32"
			/>
			<Alert v-if="createError" theme="red" :title="createError" />
		</div>
	</section>
</template>
