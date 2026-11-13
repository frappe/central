<script setup lang="ts">
import { Alert, Button, Dialog, FormControl } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import FirewallRulesEditor from '@/components/servers/firewall/FirewallRulesEditor.vue'
import { getErrorMessage } from '@/lib/feedback'
import { type FirewallRules, getRulesError, PRESETS } from '@/lib/firewall'
import { __ } from '@/lib/translate'
import type { FirewallRuleset } from '@/types/firewallRulesets'

interface Props {
	/** The ruleset to change, or null to create one. */
	ruleset: FirewallRuleset | null
	/** Names for known addresses, such as the team's WireGuard VPN devices. */
	names: Record<string, string>
	save: (title: string, rules: FirewallRules, name?: string) => Promise<void>
}

const props = defineProps<Props>()
const emit = defineEmits<{ saved: [] }>()
const open = defineModel<boolean>({ required: true })

const title = ref('')
const rules = ref<FirewallRules>({ inbound: [], outbound: [] })
const revision = ref(0)
const hasIncomplete = ref(false)
const busy = ref(false)
const error = ref('')

// A new ruleset starts from the web server rules, the same as a new server.
watch(open, (isOpen) => {
	if (!isOpen) return

	title.value = props.ruleset?.title ?? ''
	rules.value = JSON.parse(
		JSON.stringify(props.ruleset?.rules ?? PRESETS[0].rules),
	)
	hasIncomplete.value = false
	error.value = ''
	revision.value++
})

const problem = computed(() => {
	if (hasIncomplete.value)
		return __('Press Enter to add the address you typed, or clear it.')
	return (
		getRulesError(rules.value.inbound) || getRulesError(rules.value.outbound)
	)
})

async function submit(): Promise<void> {
	busy.value = true
	error.value = ''
	try {
		await props.save(title.value.trim(), rules.value, props.ruleset?.name)
		open.value = false
		emit('saved')
	} catch (failure) {
		error.value = getErrorMessage(failure, __("The ruleset couldn't be saved."))
	} finally {
		busy.value = false
	}
}
</script>

<template>
	<Dialog
		v-model="open"
		:title="ruleset ? __('Edit ruleset') : __('New ruleset')"
		size="3xl"
	>
		<div class="flex flex-col gap-5">
			<p v-if="ruleset?.server_count" class="text-p-sm text-ink-gray-6">
				{{ __('Saving changes the firewall of every server that uses this ruleset.') }}
			</p>
			<Alert
				v-if="error"
				theme="red"
				:title="__('Couldn\'t save the ruleset')"
				:description="error"
			/>
			<FormControl
				v-model="title"
				autofocus
				:label="__('Name')"
				:placeholder="__('Web servers')"
			/>
			<FirewallRulesEditor
				:rules="rules"
				:disabled="busy"
				:names="names"
				:revision="revision"
				@update="rules = $event"
				@invalid="hasIncomplete = $event"
			/>
			<p v-if="problem" class="text-p-sm text-ink-red-6" role="alert">
				{{ problem }}
			</p>
			<div class="flex justify-end gap-2">
				<Button :label="__('Cancel')" :disabled="busy" @click="open = false" />
				<Button
					:label="ruleset ? __('Save ruleset') : __('Create ruleset')"
					variant="solid"
					:loading="busy"
					:disabled="!title.trim() || !!problem"
					@click="submit"
				/>
			</div>
		</div>
	</Dialog>
</template>
