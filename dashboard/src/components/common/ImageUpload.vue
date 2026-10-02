<script setup lang="ts">
import {
	Avatar,
	Dropdown,
	type DropdownOptions,
	ErrorMessage,
	FileUploader,
	LoadingIndicator,
	type UploadedFile,
} from 'frappe-ui'

/** The document field the uploaded file is attached to. */
export interface UploadTarget {
	doctype: string
	docname: string
	fieldname: string
}

/** An image field on a document. Click the image to upload or remove it. */
interface ImageUploadProps {
	label: string
	/** Shown as initials while there is no image. */
	name: string
	image: string | null
	attachTo: UploadTarget
	shape?: 'circle' | 'square'
	busy?: boolean
}

const props = withDefaults(defineProps<ImageUploadProps>(), {
	shape: 'circle',
	busy: false,
})

const emit = defineEmits<{ change: [fileUrl: string | null] }>()

function getOptions(openFileSelector: () => void): DropdownOptions {
	const noun = props.label.toLowerCase()
	const options: DropdownOptions = [
		{
			label: `Upload a ${noun}`,
			icon: 'lucide-image-plus',
			onClick: openFileSelector,
		},
	]
	if (props.image) {
		options.push({
			label: `Remove ${noun}`,
			icon: 'lucide-trash-2',
			theme: 'red',
			onClick: () => emit('change', null),
		})
	}
	return options
}
</script>

<template>
	<FileUploader
		file-types="image/*"
		:private="false"
		optimize
		v-bind="attachTo"
		@success="(file: UploadedFile) => emit('change', file.file_url)"
	>
		<template #default="{ uploading, error, openFileSelector }">
			<p class="block text-base text-ink-gray-5">{{ label }}</p>
			<Dropdown
				:options="getOptions(openFileSelector)"
				side="right"
				align="start"
			>
				<button
					type="button"
					class="relative mt-1.5 block focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-outline-gray-3 disabled:cursor-not-allowed"
					:class="shape === 'circle' ? 'rounded-full' : 'rounded-[10px]'"
					:aria-label="`Change ${label.toLowerCase()}`"
					:disabled="busy || uploading"
				>
					<Avatar
						:image="image ?? undefined"
						:label="name"
						size="3xl"
						:shape="shape"
						class="size-16"
					/>
					<span
						v-if="busy || uploading"
						class="absolute inset-0 flex items-center justify-center bg-surface-gray-7/50"
						:class="shape === 'circle' ? 'rounded-full' : 'rounded-[10px]'"
					>
						<LoadingIndicator class="size-5 text-ink-white" />
					</span>
				</button>
			</Dropdown>
			<ErrorMessage v-if="error" class="mt-1.5" :message="error" />
		</template>
	</FileUploader>
</template>
