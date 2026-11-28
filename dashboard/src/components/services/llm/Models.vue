<script setup lang="ts">
import { Button, LoadingText, Select, Tooltip } from 'frappe-ui'
import { type Component, computed, watch } from 'vue'
import CopyableValue from '@/components/common/CopyableValue.vue'
import { useAI } from '@/composables/useAI'
import { getErrorMessage } from '@/lib/feedback'
import { capitalise } from '@/lib/format'
import { limitChips, limitsFor } from '@/lib/limits'
import type { AIDialect } from '@/types/ai'
import LucideAudioLines from '~icons/lucide/audio-lines'
import LucideBinary from '~icons/lucide/binary'
import LucideCaptions from '~icons/lucide/captions'
import LucideCircleHelp from '~icons/lucide/circle-help'
import LucideFileText from '~icons/lucide/file-text'
import LucideImage from '~icons/lucide/image'
import LucideShieldCheck from '~icons/lucide/shield-check'
import LucideType from '~icons/lucide/type'
import LucideVideo from '~icons/lucide/video'

const DIALECT_LABELS: Record<AIDialect, string> = {
	openai: 'OpenAI',
	anthropic: 'Anthropic',
}

const MODALITY_ICONS: Record<string, Component> = {
	text: LucideType,
	image: LucideImage,
	audio: LucideAudioLines,
	video: LucideVideo,
	file: LucideFileText,
	embeddings: LucideBinary,
	transcription: LucideCaptions,
}

interface Props {
	active: boolean
}

defineProps<Props>()

const { ai, models, modelsLoading, modelsError, modelsGeography, loadModels } =
	useAI()

// A plan that counts per model: each model's limits, shared by the whole team.
const showLimits = computed(() => ai.value?.spend?.limit_scope === 'Model')
const limitsOf = (model: string) =>
	limitChips(
		limitsFor(ai.value?.spend?.limits ?? [], model, modelsGeography.value),
		'for the whole team',
	)

const geographies = computed(() => ai.value?.geographies ?? [])
const geographyOptions = computed(() =>
	geographies.value.map((g) => ({ label: g.label, value: g.name })),
)

const geography = computed({
	get: () => modelsGeography.value,
	set: (name: string) => void loadModels(name),
})

const defaultGeography = computed(
	() =>
		geographies.value.find((g) => g.is_default)?.name ??
		geographies.value[0]?.name ??
		'',
)

watch(
	defaultGeography,
	(name) => {
		if (name && !geography.value) geography.value = name
	},
	{ immediate: true },
)
</script>

<template>
	<section>
		<Teleport v-if="active" defer to="#ai-tab-controls">
			<Select
				v-model="geography"
				:options="geographyOptions"
				align="end"
				:aria-label="__('Geography')"
			/>
		</Teleport>

		<LoadingText v-if="modelsLoading && !models.length" :lines="4" />

		<div
			v-else-if="modelsError && !models.length"
			class="flex items-center justify-between gap-3 rounded-5 border border-outline-gray-1 px-4 py-3"
		>
			<p class="text-p-sm text-ink-gray-6">
				{{ getErrorMessage(modelsError, "Couldn't load the models.") }}
			</p>
			<Button :label="__('Retry')" @click="loadModels(geography)" />
		</div>

		<p
			v-else-if="!models.length"
			class="rounded-5 border border-dashed border-outline-gray-2 px-4 py-8 text-center text-p-sm text-ink-gray-5"
		>
			{{ __('No models in this geography yet.') }}
		</p>

		<table
			v-else
			class="w-full border-separate border-spacing-0 text-left transition-opacity duration-200"
			:class="modelsLoading && 'opacity-60'"
		>
			<thead>
				<tr class="text-sm text-ink-gray-5">
					<th scope="col" class="hidden pb-2 font-normal md:table-cell">
						{{ __('Provider') }}
					</th>
					<th scope="col" class="hidden pb-2 font-normal md:table-cell">
						{{ __('Model') }}
					</th>
					<th scope="col" class="pb-2 font-normal">{{ __('Model key') }}</th>
					<th scope="col" class="hidden w-20 pb-2 font-normal md:table-cell">
						{{ __('Input') }}
					</th>
					<th scope="col" class="hidden w-20 pb-2 font-normal md:table-cell">
						{{ __('Output') }}
					</th>
					<th
						v-if="showLimits"
						scope="col"
						class="hidden pb-2 pr-6 font-normal lg:table-cell"
					>
						{{ __('Rate limits') }}
					</th>
					<th
						scope="col"
						class="hidden pb-2 text-right font-normal md:table-cell"
					>
						{{ __('API') }}
					</th>
				</tr>
			</thead>

			<tbody>
				<tr v-for="model in models" :key="model.name">
					<td
						class="hidden border-t border-outline-gray-1 py-2.5 pr-3 text-sm text-ink-gray-7 md:table-cell"
					>
						<span class="flex items-center gap-1.5">
							{{ model.provider_display_name }}
							<Tooltip
								v-if="model.zero_data_retention"
								:text="__('Zero data retention: the provider keeps nothing of your requests.')"
							>
								<LucideShieldCheck
									class="size-4 text-ink-gray-5"
									role="img"
									:aria-label="__('Zero data retention')"
								/>
							</Tooltip>
						</span>
					</td>

					<td
						class="hidden border-t border-outline-gray-1 py-2.5 pr-3 text-sm text-ink-gray-7 md:table-cell"
					>
						{{ model.display_name }}
					</td>

					<td
						class="border-t border-outline-gray-1 py-2.5 pr-3 md:whitespace-nowrap"
					>
						<CopyableValue :value="model.name" :label="__('Model key')" />
					</td>

					<td
						v-for="(modalities, side) in [model.input_modalities, model.output_modalities]"
						:key="side"
						class="hidden border-t border-outline-gray-1 py-2.5 pr-3 md:table-cell"
					>
						<span class="flex items-center gap-2 text-ink-gray-5">
							<Tooltip
								v-for="modality in modalities"
								:key="modality"
								:text="capitalise(modality)"
							>
								<component
									:is="MODALITY_ICONS[modality] ?? LucideCircleHelp"
									class="size-4"
									role="img"
									:aria-label="capitalise(modality)"
								/>
							</Tooltip>
						</span>
					</td>

					<td
						v-if="showLimits"
						class="hidden whitespace-nowrap border-t border-outline-gray-1 py-2.5 pr-6 text-sm text-ink-gray-6 lg:table-cell"
					>
						<span class="flex items-center gap-x-2">
							<template
								v-for="(chip, index) in limitsOf(model.name)"
								:key="chip.key"
							>
								<span v-if="index" aria-hidden="true">·</span>
								<Tooltip :text="chip.text">
									<span class="tabular-nums">{{ chip.label }}</span>
								</Tooltip>
							</template>
							<span v-if="!limitsOf(model.name).length" class="text-ink-gray-5">
								{{ __('No limit') }}
							</span>
						</span>
					</td>

					<td
						class="hidden whitespace-nowrap border-t border-outline-gray-1 py-2 text-right text-sm text-ink-gray-6 md:table-cell"
					>
						{{ model.dialects.map((dialect) => DIALECT_LABELS[dialect]).join(' · ') }}
					</td>
				</tr>
			</tbody>
		</table>
	</section>
</template>
