<script setup lang="ts">
import { computed, ref } from "vue";
import { Badge, Button, useCall } from "frappe-ui";
import BillingCard from "@/components/billing/BillingCard.vue";
import EmptyState from "@/components/common/EmptyState.vue";
import SubscribeServiceDialog from "@/components/billing/SubscribeServiceDialog.vue";
import type { ServicePlanOption } from "@/components/billing/SubscribeServiceDialog.vue";
import { API, method } from "@/api/methods";
import { useSession } from "@/composables/useSession";
import { whenTeamReady } from "@/composables/useTeamScope";
import { useCapabilities } from "@/composables/useCapabilities";

// Metered services (ADR 0015) — the team-level services it has subscribed to (AI
// tokens, email, PDF, storage), each with its allowance draw-down / usage this
// period, plus a subscribe/upgrade action. A metered service has no VM: it is a
// synthesized subject billed off the same rollup + price-lock spine as a server.
interface ServiceRow {
	service_subject: string;
	plan: string;
	title: string | null;
	cluster: string | null;
	currency: string;
	unit: string | null;
	billing_type: string | null;
	settlement_mode: string;
	reporting_mode: string;
	allowance: number;
	period_usage: number;
}
interface MeteredServices {
	currency: string;
	services: ServiceRow[];
	available_plans: ServicePlanOption[];
}

const { canManageBilling } = useCapabilities();
const { activeTeam } = useSession();

const data = useCall<MeteredServices, { team: string }>({
	url: method(API.meteredServices),
	params: () => ({ team: activeTeam.value! }),
	immediate: false,
	refetch: true,
});
whenTeamReady(() => data.reload());

const loading = computed(() => data.loading && !data.data);
const rows = computed(() => data.data?.services ?? []);
const plans = computed(() => data.data?.available_plans ?? []);
const currency = computed(() => data.data?.currency ?? "INR");

const dialogOpen = ref(false);

function subtitle(row: ServiceRow): string {
	const parts: string[] = [];
	if (row.title) parts.push(row.title);
	if (row.cluster) parts.push(row.cluster);
	return parts.join(" · ") || row.service_subject;
}

// A prepaid pack shows remaining allowance; a postpaid meter shows usage this period.
function usageLabel(row: ServiceRow): string {
	const unit = row.unit || "units";
	if (row.settlement_mode === "Prepaid Pack" && row.allowance) {
		const remaining = Math.max(0, row.allowance - row.period_usage);
		return `${remaining.toLocaleString()} / ${row.allowance.toLocaleString()} ${unit} left`;
	}
	const included = row.allowance ? ` of ${row.allowance.toLocaleString()} incl.` : "";
	return `${row.period_usage.toLocaleString()} ${unit}${included} this period`;
}

function exhausted(row: ServiceRow): boolean {
	return (
		row.settlement_mode === "Prepaid Pack" &&
		row.allowance > 0 &&
		row.period_usage >= row.allowance
	);
}
</script>

<template>
	<BillingCard
		title="Metered services"
		title-info="Team-level services billed by usage (AI tokens, email, PDF, storage) — no server required."
	>
		<template v-if="canManageBilling && plans.length" #action>
			<Button
				size="xs"
				label="Add service"
				icon-left="lucide-plus"
				@click="dialogOpen = true"
			/>
		</template>

		<div v-if="loading" class="space-y-3 py-1">
			<div v-for="i in 2" :key="i" class="flex items-center gap-3">
				<span class="size-4 shrink-0 animate-pulse rounded bg-surface-gray-2" />
				<div class="flex-1 space-y-1.5">
					<span class="block h-3.5 w-40 animate-pulse rounded bg-surface-gray-2" />
					<span class="block h-3 w-28 animate-pulse rounded bg-surface-gray-2" />
				</div>
			</div>
		</div>

		<div v-else-if="rows.length" class="divide-y divide-outline-gray-1">
			<div
				v-for="row in rows"
				:key="row.service_subject"
				class="flex items-center justify-between gap-3 py-3"
			>
				<div class="flex min-w-0 items-start gap-2.5">
					<span
						class="lucide-gauge mt-0.5 size-4 shrink-0 text-ink-gray-5"
						aria-hidden="true"
					/>
					<div class="min-w-0">
						<div class="flex items-center gap-2">
							<span class="truncate text-sm font-medium text-ink-gray-9">
								{{ row.title || row.plan }}
							</span>
							<Badge v-if="exhausted(row)" theme="orange" label="Exhausted" />
							<Badge
								v-else-if="row.settlement_mode === 'Prepaid Pack'"
								theme="blue"
								label="Prepaid"
							/>
						</div>
						<div class="truncate text-p-sm text-ink-gray-5">
							{{ subtitle(row) }}
						</div>
					</div>
				</div>
				<span class="shrink-0 text-sm font-medium tabular-nums text-ink-gray-9">
					{{ usageLabel(row) }}
				</span>
			</div>
		</div>

		<EmptyState
			v-else
			icon="lucide-gauge"
			title="No metered services"
			description="Subscribe to a usage-billed service like AI tokens, email, or PDF rendering."
		>
			<template v-if="canManageBilling && plans.length" #action>
				<Button
					variant="solid"
					theme="gray"
					label="Add service"
					@click="dialogOpen = true"
				/>
			</template>
		</EmptyState>

		<SubscribeServiceDialog
			v-model:open="dialogOpen"
			:plans="plans"
			:currency="currency"
			@subscribed="data.reload()"
		/>
	</BillingCard>
</template>
