<script setup lang="ts">
import { Divider, FormControl, TextInput } from 'frappe-ui'
import { computed, ref } from 'vue'
import { useAffiliate } from '@/composables/useAffiliate'
import { __ } from '@/lib/translate'
import AffiliateLinkBox from './AffiliateLinkBox.vue'

interface AffiliateLinkBuilderProps {
	link: string
}

const props = defineProps<AffiliateLinkBuilderProps>()

const OTHER = 'other'

const { products, sources, cookieDays } = useAffiliate()

const product = ref('')
// The page shows this tab only once the program has loaded, so the sources are here.
const source = ref<string>(sources.value[0]?.name ?? OTHER)
const otherSource = ref('')
const campaign = ref('')
const postUrl = ref('')

const productOptions = computed(() => [
	{ label: __('Frappe Cloud'), value: '' },
	...products.value.map((item) => ({ label: item.title, value: item.name })),
])

const sourceOptions = computed(() => [
	...sources.value.map((item) => ({ label: item.title, value: item.name })),
	{ label: __('Other'), value: OTHER },
])

// The backend keeps only an http or https link with a host, so the builder says so here.
const postUrlError = computed(() => {
	const value = postUrl.value.trim()
	if (!value) return ''
	try {
		const url = new URL(value)
		if (['http:', 'https:'].includes(url.protocol) && url.host) return ''
	} catch {
		// Not a URL at all.
	}
	return __(
		'Start the link with https://, such as https://discuss.frappe.io/t/...',
	)
})

const builtLink = computed(() => {
	const query = new URLSearchParams()
	const values = {
		product: product.value,
		utm_source:
			source.value === OTHER ? otherSource.value.trim() : source.value,
		utm_campaign: campaign.value.trim(),
		utm_content: postUrlError.value ? '' : postUrl.value.trim(),
	}
	for (const [key, value] of Object.entries(values)) {
		if (value) query.set(key, value)
	}
	const search = query.toString()
	return search ? `${props.link}?${search}` : props.link
})
</script>

<template>
	<div class="max-w-3xl">
		<p class="text-p-sm text-ink-gray-6">
			{{ __(
					'Make a link for a product and the place you will share it. People who click it and sign up for that product within {0} days count for you.',
					[cookieDays],
				) }}
		</p>

		<div class="mt-6 grid gap-5 sm:grid-cols-2">
			<FormControl
				v-model="product"
				type="select"
				:label="__('Product')"
				:options="productOptions"
			/>
			<div class="space-y-2">
				<FormControl
					v-model="source"
					type="select"
					:label="__('Source')"
					:options="sourceOptions"
				/>
				<FormControl
					v-if="source === OTHER"
					v-model="otherSource"
					:aria-label="__('Other source')"
					:placeholder="__('Name the site or app')"
				/>
			</div>
			<FormControl
				v-model="campaign"
				class="sm:col-span-2"
				:label="__('Campaign')"
				:placeholder="__('erpnext-hosting-guide')"
			/>
			<TextInput
				v-model="postUrl"
				class="sm:col-span-2"
				type="url"
				:placeholder="__('https://discuss.frappe.io/t/...')"
				:description="
					__('Your Campaigns table links to this post, so you can open it from there.')
				"
				:error="postUrlError"
			>
				<template #label>
					<span class="flex w-full items-center justify-between">
						{{ __('Post link') }}
						<span class="text-ink-gray-5">{{ __('Optional') }}</span>
					</span>
				</template>
			</TextInput>
		</div>

		<Divider class="my-6" />

		<AffiliateLinkBox :link="builtLink" :label="__('Your link')" />
	</div>
</template>
