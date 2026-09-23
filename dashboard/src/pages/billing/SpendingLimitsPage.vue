<script setup lang="ts">
import { Button, LoadingText } from 'frappe-ui'
import { ref } from 'vue'
import AddMethodDialog from '@/components/AddMethodDialog.vue'
import EditBillingProfileDialog from '@/components/billing/EditBillingProfileDialog.vue'
import { useBillingSetup } from '@/composables/useBillingSetup'
import { useSpendingLimits } from '@/composables/useSpendingLimits'
import { money } from '@/lib/format'

const {
	tier,
	currency,
	current: cur,
	monthlySpend,
	nextLevel,
	cycleRatio,
	resourcesUsed,
	resourceRatio,
	record,
	gates,
	levels,
	requirementsFor,
	tierLabel,
	reloadAfterMethodAdded,
} = useSpendingLimits()

const { complete, setupDialogOpen } = useBillingSetup()
const showAddMethod = ref(false)
const howOpen = ref(false)

function startFirstTier(): void {
	if (!complete.value) {
		setupDialogOpen.value = true
		return
	}
	showAddMethod.value = true
}

const DOT_CLASSES = {
	reached: 'size-2.5 bg-surface-gray-6',
	current: 'size-3 bg-surface-gray-9',
	locked: 'size-1.5 bg-surface-gray-4',
} as const
</script>

<template>
	<div class="h-full overflow-y-auto">
		<div class="mx-auto flex w-full max-w-3xl flex-col gap-8 px-6 py-8">
			<LoadingText v-if="tier.loading && !tier.data" :lines="6" />

			<template v-else-if="levels.length">
				<!-- "Current:" mirrors "Next:" below — parallel zones, labels outside
				     the boxes. Current is reference, so its values sit one size below
				     the gate values: the page's real news is the unmet gate. -->
				<section v-if="cur">
					<p class="text-p-base text-ink-gray-7">
						Current:
						<span class="font-medium text-ink-gray-9">
							{{ tierLabel(cur) }}
							tier
						</span>
					</p>

					<div
						class="mt-3 rounded-6 border border-outline-gray-2 bg-surface-base p-5"
					>
						<div class="grid gap-4 sm:grid-cols-2">
							<div>
								<p class="text-p-sm text-ink-gray-5">This cycle</p>
								<p
									class="mt-1 text-base-semibold tabular-nums"
									:class="
										cycleRatio >= 0.8 ? 'text-ink-amber-6' : 'text-ink-gray-9'
									"
								>
									{{ money(monthlySpend, currency) }}
									of
									{{ money(cur.max_spend, currency) }}
								</p>
							</div>

							<div v-if="cur.max_resource_count != null">
								<p class="text-p-sm text-ink-gray-5">Resources</p>
								<p
									class="mt-1 text-base-semibold tabular-nums"
									:class="
										resourceRatio >= 0.8
											? 'text-ink-amber-6'
											: 'text-ink-gray-9'
									"
								>
									{{ resourcesUsed }}
									of {{ cur.max_resource_count }}
								</p>
							</div>
						</div>

						<p v-if="!nextLevel" class="mt-4 text-p-base text-ink-gray-5">
							This is the highest tier
						</p>

						<p v-if="record" class="mt-4 text-p-sm text-ink-gray-5">
							{{ record }}
						</p>
					</div>
				</section>

				<!-- A team with no tier yet gets the pitch and the actual action, not
				     a pointer to another page: the first rung's concrete numbers, the
				     fear named and defused, and the next step as a button. -->
				<section
					v-else
					class="rounded-6 border border-outline-gray-2 bg-surface-base p-5"
				>
					<!-- The headline is the thing the tier lets you DO, not the tier —
				     and a team already gets its first server without one, so the
				     pitch is growing past it. -->
					<h2 class="text-xl-semibold text-ink-gray-9">
						Grow beyond your first server
					</h2>
					<!-- No figures here: the Beginner row directly below carries them. -->
					<p class="mt-1.5 text-p-base text-ink-gray-6">
						Add a payment method to start on the
						{{ tierLabel(levels[0]) }}
						tier. You only pay for what you use, and your limit rises as your
						payment history grows.
					</p>
					<Button
						class="mt-4"
						variant="solid"
						:label="complete ? 'Add payment method' : 'Add billing details'"
						@click="startFirstTier"
					/>
				</section>

				<!-- The distance to the next rung, out in the open. The gates are
				     independent AND-conditions, so they sit side by side as peers —
				     a cleared one is a check, an open one is a distance. -->
				<section v-if="nextLevel">
					<p class="text-p-base text-ink-gray-7">
						Next:
						<span class="font-medium text-ink-gray-9">
							{{ tierLabel(nextLevel) }}
							tier
						</span>
					</p>

					<!-- One bordered container, gates as joined halves: an AND reads as
					     one card with a shared wall, not two independent choices. -->
					<div
						class="mt-3 rounded-6 border border-outline-gray-2 bg-surface-base"
						:class="
							gates.length > 1
								? 'grid divide-y divide-outline-gray-2 sm:grid-cols-2 sm:divide-x sm:divide-y-0'
								: ''
						"
					>
						<div v-for="gate in gates" :key="gate.label" class="p-4">
							<p class="text-p-sm text-ink-gray-5">{{ gate.label }}</p>
							<p
								class="mt-1 flex items-center gap-1.5 text-lg-semibold tabular-nums text-ink-gray-9"
							>
								<span
									v-if="gate.done"
									class="lucide-check size-4 shrink-0 text-ink-green-5"
									aria-hidden="true"
								/>
								{{ gate.detail }}
							</p>
							<!-- Both tiles keep the bar so they share one anatomy; a done
							     gate fills it in the muted "settled" tone the rail uses,
							     the open gate keeps the dark outstanding fill. -->
							<span
								class="mt-3 block h-1 overflow-hidden rounded-full bg-surface-gray-3"
							>
								<span
									class="block h-full rounded-full transition-[width] duration-300"
									:class="gate.done ? 'bg-surface-gray-5' : 'bg-surface-gray-9'"
									:style="{
										width: `${gate.done ? 100 : Math.round(gate.ratio * 100)}%`,
									}"
								/>
							</span>
						</div>
					</div>
				</section>

				<!-- Tiers table. The rail in the leading column is doing a semantic
				     job, not a wayfinding one: it says "path you're on", where a bare
				     table of prices reads as "menu you pick from". -->
				<!-- No header row: every cell is self-labeling, and the ascending
				     price edge explains itself. Column widths live in the colgroup
				     since there are no header cells to carry them. -->
				<table class="w-full text-left text-base">
					<colgroup>
						<col class="w-7" />
						<col class="w-28" />
						<col />
						<col />
					</colgroup>

					<tbody>
						<!-- No row dividers: the rail and the row rhythm do the separating,
						     and a hairline would cut across the timeline. -->
						<tr v-for="(l, rung) in levels" :key="l.tier">
							<!-- The travelled track is solid and the road ahead is faint;
							     both stop at the first and last dots so the ladder reads
							     bounded rather than running off the table. -->
							<td class="relative">
								<!-- bg-surface-*, not bg-outline-*: outline tokens carry no
								     background value, so a faint line needs a surface tone. -->
								<span
									v-if="rung !== 0"
									class="absolute left-1/2 top-0 h-6 w-px -translate-x-1/2"
									:class="
										l.state === 'locked'
											? 'bg-surface-gray-3'
											: 'bg-surface-gray-5'
									"
									aria-hidden="true"
								/>
								<span
									v-if="rung !== levels.length - 1"
									class="absolute bottom-0 left-1/2 top-6 w-px -translate-x-1/2"
									:class="
										l.state === 'reached'
											? 'bg-surface-gray-5'
											: 'bg-surface-gray-3'
									"
									aria-hidden="true"
								/>
								<span
									class="absolute left-1/2 top-6 -translate-x-1/2 -translate-y-1/2 rounded-full"
									:class="DOT_CLASSES[l.state]"
									aria-hidden="true"
								/>
							</td>

							<!-- Rungs behind you dim as whole rows (the rail stays full
							     strength) so the eye lands on current and next. -->
							<td :class="l.state === 'reached' ? 'opacity-40' : ''">
								<span class="font-semibold text-ink-gray-9">
									{{ tierLabel(l) }}
								</span>
							</td>

							<td :class="l.state === 'reached' ? 'opacity-40' : ''">
								<ul class="flex flex-col gap-1.5">
									<li
										v-for="(req, i) in requirementsFor(l)"
										:key="i"
										class="flex items-center gap-2"
									>
										<span
											class="size-3.5 shrink-0"
											:class="
                          req.met
                            ? 'lucide-check text-ink-green-5'
                            : 'lucide-minus text-ink-gray-4'
                        "
											aria-hidden="true"
										/>
										<span
											:class="req.met ? 'text-ink-gray-9' : 'text-ink-gray-6'"
										>
											{{ req.text }}
										</span>
									</li>
								</ul>
							</td>

							<td
								class="text-right"
								:class="l.state === 'reached' ? 'opacity-40' : ''"
							>
								<span
									class="whitespace-nowrap font-semibold tabular-nums text-ink-gray-9"
								>
									{{ money(l.max_spend, currency) }}
								</span>
								<p
									v-if="l.max_resource_count != null"
									class="whitespace-nowrap text-p-sm text-ink-gray-5"
								>
									up to
									{{ l.max_resource_count }}
									resource{{ l.max_resource_count === 1 ? '' : 's' }}
								</p>
							</td>
						</tr>
					</tbody>
				</table>

				<!-- Same fold as billing's Advanced section. -->
				<section>
					<button
						class="-mx-2 flex items-center gap-1.5 rounded-5 px-2 py-1 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-outline-gray-4"
						:aria-expanded="howOpen"
						@click="howOpen = !howOpen"
					>
						<span
							class="lucide-chevron-right size-3.5 shrink-0 text-ink-gray-5 transition-transform duration-150 ease-out"
							:class="howOpen ? 'rotate-90' : ''"
						/>
						<h2 class="text-base-medium text-ink-gray-8">How tiers work</h2>
					</button>
					<ul
						v-if="howOpen"
						class="mt-3 flex list-disc flex-col gap-1.5 pl-4 text-p-base text-ink-gray-6"
					>
						<!-- Defined first — the table above leans on this word. -->
						<li>
							A resource is anything that bills while it runs: a server or a
							subscribed service.
						</li>
						<li>
							Tiers control the maximum amount your team can spend in a billing
							cycle.
						</li>
						<li>
							You move up automatically as your paid invoices and total spend
							cross each tier's bar.
						</li>
						<li>
							New teams start at the base tier. Add a payment method or prepaid
							credits to stay there.
						</li>
						<li>
							Need a higher limit now? Contact
							<a
								href="https://support.frappe.io"
								target="_blank"
								rel="noopener noreferrer"
								class="text-ink-blue-7 underline underline-offset-2 transition-opacity hover:opacity-80"
								>support</a
							>
							and we'll review your account.
						</li>
					</ul>
				</section>
			</template>

			<p v-else class="py-12 text-center text-p-sm text-ink-gray-5">
				Spending tiers aren't configured yet.
			</p>
		</div>

		<!-- The empty state's flow, in place: billing details first when the
		     profile is incomplete, then the add-method dialog. -->
		<EditBillingProfileDialog v-model="setupDialogOpen" />
		<AddMethodDialog v-model="showAddMethod" @done="reloadAfterMethodAdded" />
	</div>
</template>

<style scoped>
/* With no dividers or header, rhythm alone separates the rungs — hence a
   little more air than the old ruled table had. */
td {
	padding-top: 1rem;
	padding-bottom: 1rem;
	vertical-align: top;
}
</style>
