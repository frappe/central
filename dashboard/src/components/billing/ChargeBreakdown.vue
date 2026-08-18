<script setup lang="ts">
import { Badge } from 'frappe-ui'
import { computed } from 'vue'
import { money } from '@/lib/format'
import type { BillingLine } from '@/types/billing'

// The charge list, as both the invoice receipt and the current-cycle tray show
// it. One component because they are the same thing at two moments — what the
// month has cost so far, and what it cost once billed — and rendering it twice
// is how the two quietly stop agreeing.
//
// The shape it imposes: machines first, each one's charges grouped under the id
// the machine is known by, then everything with no machine behind it (metered
// services) below. A machine that changed size during the period carries its
// rows on a connector, because six rows under one heading otherwise read as six
// machines.
const props = withDefaults(
	defineProps<{
		lines: BillingLine[]
		currency: string
		/** Mark inferred lines. The tray shows a projection; a receipt is all fact. */
		showBasis?: boolean
	}>(),
	{ showBasis: false },
)

const servers = computed(() => props.lines.filter((li) => li.kind === 'Plan'))
const services = computed(() => props.lines.filter((li) => li.kind !== 'Plan'))

const serverGroups = computed(() => {
	const groups: {
		key: string
		name: string
		id: string | null
		lines: BillingLine[]
		total: number
	}[] = []
	for (const li of servers.value) {
		const key = li.subscription_resource || li.item
		const last = groups[groups.length - 1]
		if (last?.key === key) {
			last.lines.push(li)
			last.total += Number(li.amount || 0)
		} else {
			groups.push({
				key,
				name: li.server || li.server_id || li.item,
				// Beside the name only when it adds something: for an unnamed machine
				// the name IS the id, and printing it twice is noise.
				id: li.server_id && li.server_id !== li.server ? li.server_id : null,
				lines: [li],
				total: Number(li.amount || 0),
			})
		}
	}
	// Biggest machine first. The lines arrive grouped by resource id, which is a
	// hash — contiguity is all that ordering buys, and hash order on screen is
	// arbitrary.
	return groups.sort((a, b) => b.total - a.total)
})

// One machine needs no heading: the section is already called Servers.
const named = computed(() => serverGroups.value.length > 1)
const sum = (rows: BillingLine[]): number =>
	rows.reduce((t, li) => t + Number(li.amount || 0), 0)

function isEstimated(li: BillingLine): boolean {
	return li.basis === 'Estimated' || li.basis === 'Assumed'
}
</script>

<template>
	<div class="space-y-4">
		<section v-if="servers.length">
			<div class="mb-1 flex items-center justify-between gap-3">
				<span
					class="text-p-xs font-medium uppercase tracking-wide text-ink-gray-5"
				>
					{{ serverGroups.length === 1 ? 'Servers' : `Servers · ${serverGroups.length}` }}
				</span>
				<span class="text-p-sm tabular-nums text-ink-gray-5">
					{{ money(sum(servers), currency) }}
				</span>
			</div>

			<div
				v-for="group in serverGroups"
				:key="group.key"
				class="mb-1 last:mb-0"
			>
				<div
					v-if="named"
					class="flex items-center justify-between gap-3 pt-1.5"
				>
					<span class="flex min-w-0 items-baseline gap-2">
						<span class="truncate text-sm-medium text-ink-gray-8"
							>{{ group.name }}</span
						>
						<span
							v-if="group.id"
							class="shrink-0 font-mono text-xs text-ink-gray-4"
						>
							{{ group.id }}
						</span>
					</span>
					<span class="shrink-0 text-p-sm tabular-nums text-ink-gray-6">
						{{ money(group.total, currency) }}
					</span>
				</div>

				<!-- The connector is only drawn where a machine actually changed during
				     the period; one row is not a sequence. -->
				<ul
					:class="
            named
              ? group.lines.length > 1
                ? 'ml-[3px] border-l border-outline-gray-2 pl-4'
                : 'pl-[21px]'
              : ''
          "
				>
					<li
						v-for="(li, idx) in group.lines"
						:key="idx"
						class="relative flex items-center justify-between gap-3 py-1.5"
					>
						<span
							v-if="named && group.lines.length > 1"
							class="absolute -left-[19.5px] top-[14px] size-[7px] rounded-full bg-surface-gray-5 ring-2 ring-surface-white"
							aria-hidden="true"
						/>
						<div class="min-w-0">
							<p class="truncate text-sm text-ink-gray-8">{{ li.item }}</p>
							<p
								v-if="li.detail || li.rate"
								class="truncate text-p-sm text-ink-gray-5"
							>
								{{ li.detail }}
								<template v-if="li.rate">
									· {{ money(li.rate, currency) }}/mo</template
								>
							</p>
						</div>
						<span class="flex shrink-0 items-center gap-2 pl-3">
							<Badge
								v-if="showBasis && isEstimated(li)"
								theme="amber"
								variant="subtle"
								label="Estimated"
							/>
							<span class="text-sm tabular-nums text-ink-gray-8">
								{{ money(li.amount, currency) }}
							</span>
						</span>
					</li>
				</ul>
			</div>
		</section>

		<section v-if="services.length">
			<div class="mb-1 flex items-center justify-between gap-3">
				<span
					class="text-p-xs font-medium uppercase tracking-wide text-ink-gray-5"
				>
					Services
				</span>
				<span class="text-p-sm tabular-nums text-ink-gray-5">
					{{ money(sum(services), currency) }}
				</span>
			</div>
			<ul>
				<li
					v-for="(li, idx) in services"
					:key="idx"
					class="flex items-center justify-between gap-3 py-1.5"
				>
					<div class="min-w-0">
						<p class="truncate text-sm text-ink-gray-8">{{ li.item }}</p>
						<p v-if="li.detail" class="truncate text-p-sm text-ink-gray-5">
							{{ li.detail }}
						</p>
					</div>
					<span class="flex shrink-0 items-center gap-2 pl-3">
						<Badge
							v-if="showBasis && isEstimated(li)"
							theme="amber"
							variant="subtle"
							label="Estimated"
						/>
						<span class="text-sm tabular-nums text-ink-gray-8">
							{{ money(li.amount, currency) }}
						</span>
					</span>
				</li>
			</ul>
		</section>
	</div>
</template>
