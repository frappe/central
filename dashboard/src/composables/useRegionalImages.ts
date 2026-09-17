import { call } from 'frappe-ui'
import { computed, type Ref, ref, watch } from 'vue'
import { useSession } from '@/composables/useSession'
import { getErrorMessage } from '@/lib/toast'
import type {
	ImageOffering,
	ImageSelection,
	RegionalImage,
} from '@/types/serverCreation'

// What the build is, in the words a person uses: the Frappe version a Pilot image
// carries, or the OS version of a plain image. The internal image id says nothing.
function buildLabel(image: RegionalImage, withArchitecture: boolean): string {
	const frappe = image.tags.frappe_version
	const version = frappe
		? frappe === 'develop'
			? 'Nightly'
			: `Version ${frappe.replace('version-', '')}`
		: (image.tags.os_version ?? image.title)

	return withArchitecture ? `${version} · ${image.architecture}` : version
}

export function useRegionalImages(region: Ref<string | null>) {
	const { activeTeam } = useSession()
	const offerings = ref<ImageOffering[]>([])
	const images = ref<RegionalImage[]>([])
	const offering = ref('')
	const imageId = ref('')
	const loading = ref(false)
	const error = ref('')
	let generation = 0

	async function reload() {
		const current = ++generation
		const team = activeTeam.value
		const atlas = region.value
		images.value = []
		imageId.value = ''
		error.value = ''
		loading.value = false
		if (!team || !atlas) return

		loading.value = true
		try {
			const choices = await call<ImageOffering[]>(
				'central.api.images.list_offerings',
				{ team },
			)
			if (current !== generation) return
			offerings.value = choices
			if (!choices.some((choice) => choice.name === offering.value)) {
				offering.value = choices[0]?.name ?? ''
				return
			}
			if (!offering.value) return

			const builds: RegionalImage[] = []
			let offset: number | null = 0
			do {
				const page: { items: RegionalImage[]; next_offset: number | null } =
					await call('central.api.images.list_images', {
						team,
						atlas_instance: atlas,
						offering: offering.value,
						offset,
					})
				if (current !== generation) return
				builds.push(...page.items)
				offset = page.next_offset
			} while (offset !== null)
			images.value = builds
			// One build is not a choice; picking it here saves a required click and lets
			// the plan step load straight away.
			if (builds.length === 1) imageId.value = builds[0].id
		} catch (failure) {
			if (current === generation)
				error.value = getErrorMessage(
					failure,
					'Images could not be loaded. Retry or select another region.',
				)
		} finally {
			if (current === generation) loading.value = false
		}
	}

	watch([activeTeam, region, offering], reload, { immediate: true })
	const image = computed(
		() => images.value.find((item) => item.id === imageId.value) ?? null,
	)
	const selection = computed<ImageSelection | null>(() =>
		image.value ? { offering: offering.value, image_id: image.value.id } : null,
	)
	const imageOptions = computed(() => {
		// Architecture only earns its place when the region offers more than one.
		const mixed =
			new Set(images.value.map((item) => item.architecture)).size > 1
		return [
			{ label: 'Select an image build', value: '' },
			...images.value.map((item) => ({
				label: buildLabel(item, mixed),
				value: item.id,
			})),
		]
	})

	return {
		offerings,
		offering,
		images,
		imageId,
		image,
		selection,
		imageOptions,
		loading,
		error,
		reload,
	}
}
