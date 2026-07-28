<script setup lang="ts">
import { computed } from "vue";
import { Button, Badge, LoadingText } from "frappe-ui";
import BillingCard from "@/components/billing/BillingCard.vue";
import { useBillingOverview } from "@/composables/useBillingOverview";
import { useCapabilities } from "@/composables/useCapabilities";

// Billing contact & tax — one card combining the invoice contact (email +
// address) and tax details (region + GSTIN). Edit opens the shared profile dialog
// (owned by the page).
defineEmits<{ edit: [] }>();
const { profile } = useBillingOverview();
const { canManageBilling } = useCapabilities();

const loading = computed(() => profile.loading && !profile.data);
const email = computed(() => profile.data?.email || "");
const address = computed(() => {
	const p = profile.data;
	if (!p) return "";
	return [p.address_line1, p.address_line2, p.city, p.state, p.country, p.pincode]
		.filter(Boolean)
		.join(", ");
});
const country = computed(() => profile.data?.country || "");
const gstin = computed(() => profile.data?.gstin || "");
const isIndia = computed(() => country.value === "India");
</script>

<template>
	<BillingCard title="Billing contact & tax">
		<template #action>
			<Button
				v-if="canManageBilling"
				variant="ghost"
				size="xs"
				icon="lucide-pencil"
				aria-label="Edit billing contact & tax"
				@click="$emit('edit')"
			/>
		</template>

		<div v-if="loading" class="space-y-3">
			<LoadingText :lines="4" />
		</div>

		<dl v-else class="space-y-3 text-sm">
			<div class="flex justify-between gap-3">
				<dt class="text-ink-gray-5">Billing email</dt>
				<dd
					class="truncate text-right"
					:class="email ? 'text-ink-gray-8' : 'text-ink-gray-5'"
				>
					{{ email || "Not set" }}
				</dd>
			</div>
			<div class="flex justify-between gap-3">
				<dt class="shrink-0 text-ink-gray-5">Billing address</dt>
				<dd class="text-right" :class="address ? 'text-ink-gray-8' : 'text-ink-gray-5'">
					{{ address || "No address on file" }}
				</dd>
			</div>
			<div class="flex justify-between gap-3">
				<dt class="text-ink-gray-5">Tax region</dt>
				<dd class="text-right" :class="country ? 'text-ink-gray-8' : 'text-ink-gray-5'">
					{{ country || "Not set" }}
				</dd>
			</div>
			<div v-if="isIndia" class="flex items-center justify-between gap-3">
				<dt class="text-ink-gray-5">GSTIN</dt>
				<dd v-if="gstin" class="text-right font-mono text-ink-gray-8">
					{{ gstin }}
				</dd>
				<Badge v-else theme="gray" label="Not provided" />
			</div>
		</dl>
	</BillingCard>
</template>
