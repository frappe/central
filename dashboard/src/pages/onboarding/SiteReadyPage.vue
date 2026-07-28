<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { Button, ErrorMessage } from "frappe-ui";
import { useRoute } from "vue-router";
import AuthShell from "@/components/auth/AuthShell.vue";
import { API } from "@/api/methods";
import { frappeErrorMessage, getFrappe, methodUrl } from "@/lib/auth";

type SiteState = {
	name: string;
	status: string;
	url: string | null;
	login_url: string | null;
};

const POLL_MS = 1000;

const route = useRoute();
const name = String(route.params.name ?? "");

const site = ref<SiteState | null>(null);
const error = ref("");
let timer: ReturnType<typeof setTimeout> | undefined;

const isReady = computed(() => site.value?.status === "Running");
const isFailed = computed(() => site.value?.status === "Failed");

async function poll() {
	try {
		const result = await getFrappe<SiteState>(methodUrl(API.getSite), { name });
		site.value = result;
		if (result.status === "Running") return signIn();
		if (result.status === "Failed") return;
	} catch (exception) {
		error.value = frappeErrorMessage(exception, "Lost track of your site. Refresh to retry.");
		return;
	}
	timer = setTimeout(poll, POLL_MS);
}

// The site is ready: log the tenant straight in by navigating this tab to the
// one-click login URL. No button, no password — the poll landing on Running IS
// the handoff. If the site somehow reported Running without a login URL, fall
// through to the manual state so the tenant isn't stranded.
function signIn() {
	const url = site.value?.login_url;
	if (!url) return;
	window.location.assign(url);
}

onMounted(poll);
onUnmounted(() => clearTimeout(timer));
</script>

<template>
	<AuthShell show-progress :step="4">
		<template v-if="isReady && site">
			<div
				class="mb-6 grid size-10 place-items-center rounded-5 bg-surface-green-3 text-ink-green-8"
			>
				<span class="lucide-check size-5" aria-hidden="true" />
			</div>
			<h1 class="text-2xl font-semibold text-ink-gray-9">Your site is ready</h1>
			<p class="mt-2 text-base text-ink-gray-5">
				Signing you in to
				<span class="font-medium text-ink-gray-8">{{ site.url }}</span> as
				<span class="font-medium text-ink-gray-8">Administrator</span>…
			</p>

			<div class="mt-8 flex items-center gap-3 text-ink-gray-5">
				<span class="lucide-loader-circle size-5 animate-spin" aria-hidden="true" />
				<span class="text-base">Taking you to your site…</span>
			</div>
		</template>

		<template v-else-if="isFailed">
			<h1 class="text-2xl font-semibold text-ink-gray-9">Setup didn't finish</h1>
			<p class="mt-2 text-base text-ink-gray-5">
				We couldn't finish setting up your site. Pick a different name and try again.
			</p>
			<RouterLink to="/onboarding/site" class="mt-8 block">
				<Button variant="solid" size="md" class="w-full">Try again</Button>
			</RouterLink>
		</template>

		<template v-else>
			<h1 class="text-2xl font-semibold text-ink-gray-9">Setting up ERPNext…</h1>
			<p class="mt-2 text-base text-ink-gray-5">
				We're provisioning
				<span class="font-medium text-ink-gray-8">{{ name }}</span
				>. This takes a moment — hang tight.
			</p>
			<div class="mt-8 flex items-center gap-3 text-ink-gray-5">
				<span class="lucide-loader-circle size-5 animate-spin" aria-hidden="true" />
				<span class="text-base">{{ site?.status || "Pending" }}…</span>
			</div>
			<ErrorMessage v-if="error" class="mt-6" :message="error" />
		</template>
	</AuthShell>
</template>
