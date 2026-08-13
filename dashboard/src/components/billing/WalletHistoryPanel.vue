<script setup lang="ts">
import { Button, LoadingText, Switch } from 'frappe-ui'
import { computed, ref } from 'vue'
import TopupDialog from '@/components/TopupDialog.vue'
import SidePanel from '@/components/common/SidePanel.vue'
import { useBillingOverview } from '@/composables/useBillingOverview'
import { useBillingSetup } from '@/composables/useBillingSetup'
import { useCapabilities } from '@/composables/useCapabilities'
import { money, signedMoney } from '@/lib/format'
import { infoToast } from '@/lib/toast'
import type { CreditLedgerEntry } from '@/types/billing'

// Wallet history — a docked side panel (like the invoice detail tray), opened
// from the compact Wallet card. Balance header, auto-recharge toggle, the credit
// ledger, and Add credit (TopupDialog → #67). The page owns whether it's mounted;
// the close button clears that.
const open = defineModel<boolean>('open', { default: false })
const { credit, ledger, currency, reloadMoney } = useBillingOverview()
const { canManageBilling } = useCapabilities()
const { requireSetup } = useBillingSetup()

const balance = computed(() => Number(credit.data?.balance ?? 0))

// GROUNDING GAP (#69): no auto-recharge endpoint yet. The toggle is rendered to
// match the design but is inert until one lands.
const autoRecharge = ref(false)
function onAutoRecharge(): void {
	autoRecharge.value = false
	infoToast("Auto-recharge isn't available yet")
}

const showTopup = ref(false)
function onAddCredit(): void {
	if (requireSetup()) showTopup.value = true
}

function isCredit(entry: CreditLedgerEntry): boolean {
	return Number(entry.amount) >= 0 && entry.entry_type !== 'Debit'
}
</script>

<template>
	<!-- The shared docked SidePanel (billing invoice anatomy). -->
	<SidePanel
		v-model:open="open"
		title="Wallet history"
		:subtitle="`Balance ${money(balance, currency)}`"
	>
		<!-- Auto-recharge — the Switch's own label prop, so clicking the text
           toggles it too (the label is wired to the control, not beside it). -->
		<div class="border-b border-outline-gray-1 px-4 pb-3 pt-1.5">
			<Switch
				label="Auto-recharge"
				:model-value="autoRecharge"
				:disabled="!canManageBilling"
				@update:model-value="onAutoRecharge"
			/>
		</div>

			<!-- Ledger. No inner scroll: SidePanel's body already scrolls, and a
			     second scroller here traps the ledger in a short box — worst on the
			     mobile sheet, where the panel is the full screen and the ledger got
			     a sliver of it. Same fix the invoice receipt took. -->
			<div>
				<div v-if="ledger.loading && !ledger.data" class="space-y-3 p-4">
					<LoadingText :lines="5" />
				</div>
				<div
					v-else-if="!ledger.data?.length"
					class="px-4 py-12 text-center text-p-sm text-ink-gray-5"
				>
					No credit activity yet.
				</div>
				<ul v-else class="divide-y divide-outline-gray-1">
					<li
						v-for="(e, idx) in ledger.data"
						:key="idx"
						class="flex items-center gap-3 px-4 py-3"
					>
						<span
							class="grid size-8 shrink-0 place-items-center rounded-full"
							:class="isCredit(e) ? 'bg-surface-green-2' : 'bg-surface-gray-2'"
						>
							<span
								class="size-4"
								:class="
                isCredit(e)
                  ? 'lucide-arrow-down-left text-ink-green-7'
                  : 'lucide-arrow-up-right text-ink-gray-6'
              "
								aria-hidden="true"
							/>
						</span>
						<div class="min-w-0 flex-1">
							<p class="truncate text-sm text-ink-gray-8">
								{{ e.note || e.entry_type }}
							</p>
							<p class="text-p-sm text-ink-gray-5">{{ e.created_at }}</p>
						</div>
						<span
							class="shrink-0 text-sm tabular-nums"
							:class="isCredit(e) ? 'text-ink-green-7' : 'text-ink-gray-8'"
						>
							{{ signedMoney(e.amount, e.currency || currency, isCredit(e)) }}
						</span>
					</li>
				</ul>
			</div>

		<TopupDialog
			v-model="showTopup"
			:currency="currency"
			@done="reloadMoney"
		/>

		<template v-if="canManageBilling" #footer>
			<Button
				variant="solid"
				theme="gray"
				label="Add credit"
				class="w-full"
				@click="onAddCredit"
			>
				<template #prefix
					><span class="lucide-plus size-4" aria-hidden="true" /></template
				>
			</Button>
		</template>
	</SidePanel>
</template>
