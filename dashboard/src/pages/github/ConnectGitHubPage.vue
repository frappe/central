<script setup lang="ts">
import {
	Avatar,
	Badge,
	Button,
	Checkbox,
	ErrorMessage,
	LoadingText,
	ScrollArea,
	TextInput,
} from 'frappe-ui'
import { computed, ref, watchEffect } from 'vue'
import { useRoute } from 'vue-router'
import frappeCloudLogo from '@/assets/fc-logo.svg'
import { useGitHubConnection } from '@/composables/useGitHubConnection'

const route = useRoute()
const {
	connection,
	loading,
	loadError,
	installations,
	installationId,
	repositories,
	repositoriesLoading,
	repositoriesError,
	selections,
	selected,
	selectedCount,
	hasChanges,
	toggle,
	detach,
	grant,
	busy,
	error,
} = useGitHubConnection((route.params.attempt as string | undefined) ?? '')

const query = ref('')

const visibleRepositories = computed(() => {
	const text = query.value.trim().toLowerCase()
	return repositories.value
		.filter(
			(repository) =>
				!text || repository.full_name.toLowerCase().includes(text),
		)
		.sort((a, b) => Number(b.is_admin) - Number(a.is_admin))
})

const installationSettingsUrl = computed(() => {
	const installation = installations.value.find(
		(item) => item.installation_id === installationId.value,
	)
	if (!installation) return ''
	const owner =
		installation.account_type === 'Organization'
			? `organizations/${installation.account}/`
			: ''
	return `https://github.com/${owner}settings/installations/${installation.installation_id}`
})

function goTo(url: string) {
	window.location.assign(url)
}

const authorizeRedirectUrl = computed(() => {
	const attempt = connection.value
	return attempt &&
		!attempt.is_authorized &&
		!attempt.is_expired &&
		!route.query.cancelled
		? attempt.authorize_url
		: ''
})

watchEffect(() => {
	if (authorizeRedirectUrl.value)
		window.location.replace(authorizeRedirectUrl.value)
})

const grantLabel = computed(() => {
	const count = selectedCount.value
	if (!count) return 'Save changes'
	return count === 1
		? 'Grant access to 1 repository'
		: `Grant access to ${count} repositories`
})
</script>

<template>
	<main class="flex min-h-screen flex-col bg-surface-base px-4">
		<section class="mx-auto w-full max-w-[480px] flex-1 pb-12 pt-16 sm:pt-24">
			<div class="mb-8 flex items-center gap-3">
				<img :src="frappeCloudLogo" alt="" class="size-9 rounded-6" />
				<span
					class="lucide-arrow-left-right size-4 text-ink-gray-4"
					aria-hidden="true"
				/>
				<span
					class="grid size-9 place-items-center rounded-6 bg-surface-gray-2 text-ink-gray-8"
				>
					<svg
						viewBox="0 0 16 16"
						class="size-5"
						fill="currentColor"
						aria-hidden="true"
					>
						<path
							d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"
						/>
					</svg>
				</span>
			</div>

			<LoadingText
				v-if="loading || authorizeRedirectUrl"
				:text="authorizeRedirectUrl ? 'Redirecting to GitHub' : 'Loading'"
			/>

			<template v-else-if="loadError || connection?.is_expired">
				<h1 class="text-2xl font-semibold text-ink-gray-9">
					{{ loadError ? "Can't connect GitHub" : 'This link has expired' }}
				</h1>
				<p class="mt-1 text-p-base text-ink-gray-5">
					{{ loadError || 'Go back to your server and click Connect GitHub again.' }}
				</p>
				<Button
					class="mt-6 w-full"
					size="md"
					variant="solid"
					:label="connection?.return_url ? 'Back to your server' : 'Open Frappe Cloud'"
					@click="goTo(connection?.return_url || '/dashboard/servers')"
				/>
			</template>

			<template v-else-if="connection">
				<h1 class="text-2xl font-semibold text-ink-gray-9">Connect GitHub</h1>
				<p class="mt-1 text-p-base text-ink-gray-5">
					Give {{ connection.server || 'this server' }} read-only access to the
					repositories you choose.
				</p>

				<div v-if="!connection.is_authorized" class="mt-6">
					<Button
						class="w-full"
						size="md"
						variant="solid"
						label="Continue with GitHub"
						@click="goTo(connection.authorize_url)"
					/>
				</div>

				<div v-else-if="!installations.length" class="mt-6 space-y-4">
					<p class="text-p-base text-ink-gray-7">
						Install the Frappe Cloud GitHub App on the account that owns your
						repositories.
					</p>
					<Button
						class="w-full"
						size="md"
						variant="solid"
						label="Install on GitHub"
						@click="goTo(connection.install_url)"
					/>
				</div>

				<div v-else class="mt-6 space-y-6">
					<div class="space-y-2">
						<div class="flex items-center justify-between">
							<span class="text-sm font-medium text-ink-gray-8">Account</span>
							<div class="flex items-center gap-3 text-sm text-ink-gray-6">
								<button
									v-if="selected.size"
									type="button"
									class="underline-offset-2 hover:underline"
									@click="detach"
								>
									Detach
								</button>
								<a
									v-else-if="installationSettingsUrl"
									:href="installationSettingsUrl"
									class="underline-offset-2 hover:underline"
									>Manage on GitHub</a
								>
							</div>
						</div>
						<div class="flex flex-wrap gap-2">
							<button
								v-for="installation in installations"
								:key="installation.installation_id"
								type="button"
								class="flex items-center gap-2 rounded-8 border px-3 py-2 text-sm transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-outline-gray-4"
								:class="
									installationId === installation.installation_id
										? 'border-outline-gray-5 bg-surface-gray-2 text-ink-gray-9'
										: 'border-outline-gray-2 text-ink-gray-7 hover:bg-surface-gray-1'
								"
								@click="installationId = installation.installation_id"
							>
								<Avatar
									:image="installation.avatar_url"
									:label="installation.account"
									size="sm"
								/>
								{{ installation.account }}
								<span
									v-if="selections[installation.installation_id]?.size"
									class="text-ink-gray-5"
									>{{ selections[installation.installation_id].size }}</span
								>
							</button>
							<a
								:href="connection.install_url"
								class="flex items-center gap-1.5 rounded-8 border border-dashed border-outline-gray-2 px-3 py-2 text-sm text-ink-gray-6 transition-colors hover:bg-surface-gray-1 hover:text-ink-gray-8"
							>
								<span class="lucide-plus size-4" aria-hidden="true" />
								Add account
							</a>
						</div>
					</div>

					<div class="space-y-2">
						<div class="flex items-center justify-between">
							<span class="text-sm font-medium text-ink-gray-8"
								>Repositories</span
							>
							<a
								:href="connection.install_url"
								class="text-sm text-ink-gray-6 underline-offset-2 hover:underline"
								>Missing one?</a
							>
						</div>
						<TextInput v-model="query" placeholder="Search repositories" />
						<ScrollArea viewport-class="max-h-80">
							<LoadingText
								v-if="repositoriesLoading"
								class="p-4"
								text="Loading repositories"
							/>
							<ErrorMessage
								v-else-if="repositoriesError"
								class="p-4"
								:message="repositoriesError"
							/>
							<p
								v-else-if="!visibleRepositories.length"
								class="p-4 text-p-sm text-ink-gray-5"
							>
								No repositories found.
							</p>
							<div v-else class="flex flex-col gap-0.5">
								<Checkbox
									v-for="repository in visibleRepositories"
									:key="repository.repository_id"
									padded
									size="md"
									:model-value="selected.has(repository.repository_id)"
									:disabled="!repository.is_admin"
									:description="
										repository.is_admin ? '' : 'Needs admin access on GitHub'
									"
									@update:model-value="toggle(repository.repository_id)"
								>
									<template #label>
										<span class="flex items-center gap-2">
											{{ repository.full_name }}
											<Badge
												v-if="repository.private"
												label="Private"
												theme="gray"
												size="sm"
											/>
										</span>
									</template>
								</Checkbox>
							</div>
						</ScrollArea>
					</div>

					<ErrorMessage v-if="error" :message="error" />
					<Button
						class="w-full"
						size="md"
						variant="solid"
						:label="grantLabel"
						:disabled="!hasChanges"
						:loading="busy"
						@click="grant"
					/>
				</div>

				<a
					v-if="connection.return_url"
					:href="connection.return_url"
					class="mt-6 flex items-center justify-center gap-1 text-sm text-ink-gray-5 hover:text-ink-gray-8"
				>
					<span class="lucide-arrow-left size-4" aria-hidden="true" />
					Back without connecting
				</a>
			</template>
		</section>
	</main>
</template>
