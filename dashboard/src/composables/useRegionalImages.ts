import { call, frappeRequest } from 'frappe-ui'
import { computed, type Ref, ref, watch } from 'vue'
import { API, methodV1 } from '@/api/methods'
import { useSession } from '@/composables/useSession'
import { formatUnixTime } from '@/lib/format'
import { getErrorMessage } from '@/lib/toast'
import type {
	ImageOffering,
	ImageSelection,
	RegionalImage,
} from '@/types/serverCreation'
import type { SnapshotList, VMSnapshotRow } from '@/types/snapshots'

// What the build is, in the words a person uses: the Frappe version a Pilot image
// carries, or the OS version of a plain image. The internal image id says nothing.
function versionLabel(image: RegionalImage): string {
	const frappe = image.tags.frappe_version
	if (!frappe) return image.tags.os_version ?? image.title
	return frappe === 'develop'
		? 'Nightly'
		: `Version ${frappe.replace('version-', '')}`
}

// A region carries one build per release, so a version on its own names several of them.
// The build time is what tells them apart and says which one is current.
function buildLabel(image: RegionalImage, withArchitecture: boolean): string {
	const parts = [versionLabel(image), formatUnixTime(image.created_at)]
	if (withArchitecture) parts.push(image.architecture)
	return parts.filter(Boolean).join(' · ')
}

export type ImageSource = 'image' | 'snapshot'

// A snapshot restores into a server of its source's kind, so it stands in for an image
// build. Its tags are empty: Central applies the source offering's tags itself.
function snapshotAsImage(snapshot: VMSnapshotRow): RegionalImage {
	return {
		id: snapshot.atlas_image_id ?? '',
		title: snapshot.title,
		architecture: '',
		rootfs_size_mib: snapshot.size_mib,
		created_at: 0,
		tags: {},
	}
}

export function useRegionalImages(
	region: Ref<string | null>,
	initialSnapshot = '',
) {
	const { activeTeam } = useSession()
	const source = ref<ImageSource>(initialSnapshot ? 'snapshot' : 'image')
	const snapshots = ref<VMSnapshotRow[]>([])
	const snapshotName = ref(initialSnapshot)
	const snapshotsLoading = ref(false)
	const snapshotsError = ref('')
	let snapshotGeneration = 0

	async function reloadSnapshots() {
		const current = ++snapshotGeneration
		snapshots.value = []
		snapshotsError.value = ''
		if (!activeTeam.value || !region.value) return

		snapshotsLoading.value = true
		try {
			const list = await frappeRequest<SnapshotList>({
				url: methodV1(API.listSnapshots),
				method: 'GET',
				params: { team: activeTeam.value },
			})
			if (current !== snapshotGeneration) return
			snapshots.value = list.snapshots.filter(
				(row) =>
					row.region === region.value &&
					row.status === 'Available' &&
					row.is_restorable,
			)
			if (!snapshots.value.some((row) => row.name === snapshotName.value))
				snapshotName.value = ''
		} catch (failure) {
			if (current === snapshotGeneration)
				snapshotsError.value = getErrorMessage(
					failure,
					'Snapshots could not be loaded.',
				)
		} finally {
			if (current === snapshotGeneration) snapshotsLoading.value = false
		}
	}
	watch([activeTeam, region], reloadSnapshots, { immediate: true })
	const snapshot = computed(
		() =>
			snapshots.value.find((row) => row.name === snapshotName.value) ?? null,
	)
	const snapshotOptions = computed(() => [
		{ label: 'Select a snapshot', value: '' },
		...snapshots.value.map((row) => ({
			label: `${row.title} · ${row.server_title} · ${row.size_gib} GB`,
			value: row.name,
		})),
	])

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
	const image = computed<RegionalImage | null>(() => {
		if (source.value === 'snapshot')
			return snapshot.value ? snapshotAsImage(snapshot.value) : null
		return images.value.find((item) => item.id === imageId.value) ?? null
	})
	const selection = computed<ImageSelection | null>(() => {
		if (source.value === 'snapshot')
			return snapshot.value
				? {
						offering: snapshot.value.image_offering ?? '',
						image_id: snapshot.value.atlas_image_id ?? '',
						snapshot: snapshot.value.name,
					}
				: null
		return image.value
			? { offering: offering.value, image_id: image.value.id }
			: null
	})
	const imageOptions = computed(() => {
		// Architecture only earns its place when the region offers more than one.
		const mixed =
			new Set(images.value.map((item) => item.architecture)).size > 1
		// Versions stay together and the newest build of each leads its group, so the
		// current build of a version is the first one under its name.
		const builds = [...images.value].sort(
			(a, b) =>
				versionLabel(a).localeCompare(versionLabel(b)) ||
				b.created_at - a.created_at,
		)
		return [
			{ label: 'Select an image build', value: '' },
			...builds.map((item) => ({
				label: buildLabel(item, mixed),
				value: item.id,
			})),
		]
	})

	return {
		source,
		snapshots,
		snapshotName,
		snapshot,
		snapshotOptions,
		snapshotsLoading,
		snapshotsError,
		reloadSnapshots,
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
