<script setup lang="ts">
import { Badge, Button, Spinner, Tooltip } from 'frappe-ui'
import { NumberCard } from 'frappe-ui/charts'
import { type Component, computed, ref } from 'vue'
import { useAI } from '@/composables/useAI'
import { formatDateTime } from '@/lib/datetime'
import type { AIDialect } from '@/types/ai'
import LucideAudioLines from '~icons/lucide/audio-lines'
import LucideBinary from '~icons/lucide/binary'
import LucideCaptions from '~icons/lucide/captions'
import LucideCircleHelp from '~icons/lucide/circle-help'
import LucideFileText from '~icons/lucide/file-text'
import LucideImage from '~icons/lucide/image'
import LucideType from '~icons/lucide/type'
import LucideVideo from '~icons/lucide/video'

const dialectLabels: Record<AIDialect, string> = {
	openai: 'OpenAI',
	anthropic: 'Anthropic',
}
// Keyed by Grove's Modality names, which it sends lowercased. An unknown one falls
// back to a help icon.
const modalityIcons: Record<string, Component> = {
	text: LucideType,
	image: LucideImage,
	audio: LucideAudioLines,
	video: LucideVideo,
	file: LucideFileText,
	embeddings: LucideBinary,
	transcription: LucideCaptions,
}

function modalityLabel(modality: string): string {
	return modality.charAt(0).toUpperCase() + modality.slice(1)
}
const { ai, aiLoading, models } = useAI()

const usage = computed(() => ai.value?.usage ?? null)
const balance = computed(() => ai.value?.balance ?? null)

// A model call often costs a fraction of a cent, so small amounts keep 4 places.
const usdPrecision = (value: number): number => (value > 0 && value < 1 ? 4 : 2)

// The table starts short; the rest unfolds in place.
const SHOWN = 6
const showAll = ref(false)
const shownModels = computed(() =>
	showAll.value ? models.value : models.value.slice(0, SHOWN),
)
</script>

<template>
	<div class="min-h-0 flex-1 overflow-y-auto">
		<div class="mx-auto w-full max-w-3xl px-6 pb-8 pt-5">
			<div v-if="aiLoading && !ai" class="flex justify-center py-16">
				<Spinner class="size-5 text-ink-gray-5" />
			</div>

			<template v-else>
				<h2 class="text-base font-semibold text-ink-gray-8">This month</h2>

				<p class="mt-0.5 text-p-sm text-ink-gray-5">
					Across every key of the team, as of
					{{ usage?.as_of ? formatDateTime(usage.as_of) : 'the last count' }}.
				</p>

				<div class="mt-3 grid grid-cols-2 gap-4 md:grid-cols-4">
					<NumberCard
						title="Balance"
						:value="balance?.balance ?? null"
						prefix="$"
						:precision="usdPrecision(balance?.balance ?? 0)"
					/>
					<NumberCard
						title="Spent"
						:value="usage?.cost ?? null"
						prefix="$"
						:precision="usdPrecision(usage?.cost ?? 0)"
					/>
					<NumberCard title="Requests" :value="usage?.requests ?? null" />
					<NumberCard title="Tokens" :value="usage?.tokens ?? null">
						<template #actions>
							<Tooltip
								text="Prompt and completion tokens together, across every model and key."
							>
								<lucide-circle-help
									class="size-4 text-ink-gray-5"
									aria-label="What counts as a token"
								/>
							</Tooltip>
						</template>
					</NumberCard>
				</div>

				<h2
					class="text-base font-semibold text-ink-gray-8 mt-8 border-t border-outline-gray-2 pt-8"
				>
					Accessible models
				</h2>

				<p class="mt-0.5 text-p-sm text-ink-gray-5">
					The models your keys can call, what each one takes and gives, and the
					APIs it answers on.
				</p>

				<table v-if="models.length" class="mt-3 w-full border-collapse">
					<thead>
						<tr
							class="border-b border-outline-gray-2 text-p-xs text-ink-gray-5"
						>
							<th scope="col" class="py-2 pr-3 text-left font-normal">Model</th>
							<th scope="col" class="py-2 pr-3 text-left font-normal">Input</th>
							<th scope="col" class="py-2 pr-3 text-left font-normal">
								Output
							</th>
							<th scope="col" class="py-2 text-right font-normal">API</th>
						</tr>
					</thead>

					<tbody class="divide-y divide-outline-gray-1">
						<tr v-for="model in shownModels" :key="model.name">
							<td
								class="py-3 pr-3 font-mono text-sm font-medium text-ink-gray-9"
							>
								{{ model.name }}
							</td>

							<td
								v-for="(modalities, side) in [model.input_modalities, model.output_modalities]"
								:key="side"
								class="py-3 pr-3"
							>
								<div class="flex items-center gap-1.5 text-ink-gray-6">
									<Tooltip
										v-for="modality in modalities"
										:key="modality"
										:text="modalityLabel(modality)"
									>
										<component
											:is="modalityIcons[modality] ?? LucideCircleHelp"
											class="size-4"
											role="img"
											:aria-label="modalityLabel(modality)"
										/>
									</Tooltip>
								</div>
							</td>

							<td class="py-3">
								<div class="flex justify-end gap-1.5">
									<Badge
										v-for="dialect in model.dialects"
										:key="dialect"
										:label="dialectLabels[dialect]"
									/>
								</div>
							</td>
						</tr>
					</tbody>
				</table>

				<p v-else class="mt-3 text-p-sm text-ink-gray-5">
					No models accessible yet.
				</p>

				<Button
					v-if="models.length > SHOWN"
					class="-ml-2 mt-3"
					variant="ghost"
					:label="showAll ? 'Show fewer' : `Show all ${models.length}`"
					:icon-right="showAll ? 'lucide-chevron-up' : 'lucide-chevron-down'"
					@click="showAll = !showAll"
				/>
			</template>
		</div>
	</div>
</template>
