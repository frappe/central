import { expect, type Page, test } from '@playwright/test'

const plan = (
	name: string,
	cpu: number,
	memory: number,
	disk: number,
	rate: number,
) => ({
	plan: name,
	title: name,
	sub_category: 'General',
	billing_cycle: 'Monthly',
	currency: 'INR',
	cluster: 'test-region',
	rate,
	includes: [
		{ resource_type: 'Compute', quantity: cpu, unit: 'vCPU' },
		{ resource_type: 'Memory', quantity: memory, unit: 'GB' },
		{ resource_type: 'Disk', quantity: disk, unit: 'GB' },
	],
})

async function openControls(
	page: Page,
	available = 10000,
	missingDiskRate = false,
	spendLimitEnforced = true,
): Promise<void> {
	await page.route('**/api/v2/method/**', async (route) => {
		const method = new URL(route.request().url()).pathname.split('.').pop()
		let data: unknown = null
		if (method === 'my_teams')
			data = [{ name: 'test-team', label: 'Test team' }]
		if (method === 'get_composed_config')
			data = {
				resizable: true,
				subscription: 'test-sub',
				composed: false,
				plan: 'current',
				sub_category: 'General',
				vcpus: 0.5,
				memory_gb: 2,
				disk_gb: 25,
			}
		if (method === 'get_eligible_plans')
			data = {
				team: 'test-team',
				cluster: 'test-region',
				currency: 'INR',
				available,
				spend_limit_enforced: spendLimitEnforced,
				plans: {
					General: [
						plan('small', 0.125, 0.5, 10, 240),
						plan('current', 0.5, 2, 25, 950),
						plan('large', 1, 4, 50, 1900),
					],
				},
				rate_card: {
					Compute: { rate: 500, unit: 'vCPU' },
					Memory: { rate: 250, unit: 'GB' },
					...(!missingDiskRate ? { Disk: { rate: 10, unit: 'GB' } } : {}),
				},
				profiles: [
					{
						sub_category: 'General',
						ram_ratio: 4,
						vcpu_steps: [0.125, 0.25, 0.5, 1, 2],
						disk_steps: [10, 20, 40, 80],
						disk_min: 10,
						disk_max: 80,
					},
				],
			}
		if (method === 'resize_server') data = { queued: true, resized: true }
		if (method === 'update_server_firewall') data = { 'test-vm': null }
		await route.fulfill({ json: { data } })
	})
	await page.goto('/tests/server-controls.html')
}

async function openResize(page: Page): Promise<void> {
	await page.getByRole('button', { name: 'Resize server', exact: true }).click()
	await expect(
		page.getByRole('radio', { name: 'Keep current 25 GB disk size' }),
	).toBeVisible()
}

async function removeSSH(page: Page): Promise<void> {
	await page
		.getByRole('button', { name: 'Remove SSH rule', exact: true })
		.click()
}

async function discardChanges(page: Page): Promise<void> {
	await page.getByRole('button', { name: 'Discard', exact: true }).click()
	await page
		.getByRole('button', { name: 'Discard changes', exact: true })
		.click()
}

test('retained storage has the same price on the card, summary and submitted target', async ({
	page,
}, testInfo) => {
	await openControls(page)
	await openResize(page)
	const small = page.getByRole('button', { name: /0.125 vCPU/ })
	await expect(small).toContainText('₹390')
	await expect(small).toContainText('25 GB disk')
	await small.click()
	await expect(page.getByText('After resizing')).toBeVisible()
	await expect(page.getByText('₹390/mo', { exact: true })).toBeVisible()
	await page.screenshot({ path: testInfo.outputPath('resize.png') })
	const request = page.waitForRequest('**/central.api.servers.resize_server')
	await page.getByRole('button', { name: 'Resize', exact: true }).click()
	expect((await request).postDataJSON()).toMatchObject({
		plan: 'small',
		disk_gigabytes: 25,
	})
})

test('switching to plan storage clears an incompatible selection', async ({
	page,
}) => {
	await openControls(page)
	await openResize(page)
	await page.getByRole('button', { name: /0.125 vCPU/ }).click()
	await page.getByRole('radio', { name: 'Increase storage' }).click()
	const small = page.getByRole('button', { name: /0.125 vCPU/ })
	await expect(small).toBeDisabled()
	await expect(small).toHaveAttribute('aria-pressed', 'false')
	await expect(
		page.getByRole('button', { name: 'Resize', exact: true }),
	).toBeDisabled()
})

test('custom disk cannot shrink and the designer submits the displayed disk', async ({
	page,
}) => {
	await openControls(page)
	await openResize(page)
	await page.getByRole('button', { name: /Custom/ }).click()
	await expect(
		page.getByText('No restart needed.', { exact: false }),
	).toBeVisible()
	await page.getByRole('radio', { name: 'Increase storage' }).click()
	const storage = page.getByRole('button', { name: '25 GB', exact: true })
	await storage.click()
	await expect(
		page.getByRole('menuitem', { name: '10 GB', exact: true }),
	).toHaveCount(0)
	await expect(
		page.getByRole('menuitem', { name: '20 GB', exact: true }),
	).toHaveCount(0)
	await page.getByRole('menuitem', { name: '40 GB', exact: true }).click()
	await expect(page.getByText('After resizing').locator('..')).toContainText(
		'40 GB',
	)
	const request = page.waitForRequest('**/central.api.servers.resize_server')
	await page.getByRole('button', { name: 'Resize', exact: true }).click()
	expect((await request).postDataJSON()).toMatchObject({
		disk_gigabytes: 40,
		includes: expect.arrayContaining([
			{ resource_type: 'Disk', quantity: 40, unit: 'GB' },
		]),
	})
})

test('retained storage cannot bypass the spending limit or a missing rate', async ({
	page,
}) => {
	await openControls(page, 300)
	await openResize(page)
	await expect(page.getByRole('button', { name: /0.125 vCPU/ })).toBeDisabled()
	await page.unrouteAll()
	await openControls(page, 10000, true)
	await openResize(page)
	await expect(page.getByRole('button', { name: /0.125 vCPU/ })).toContainText(
		'Price unavailable',
	)
	await expect(page.getByRole('button', { name: /0.125 vCPU/ })).toBeDisabled()
})

test('removal hides the rule until Undo, Mod+Z or Discard, and a refresh keeps the draft', async ({
	page,
}, testInfo) => {
	await openControls(page)
	const sshRule = page.getByRole('button', { name: 'Remove SSH rule' })
	await removeSSH(page)
	await expect(sshRule).toHaveCount(0)
	await expect(page.getByText('1 unsaved change')).toBeVisible()
	await page.screenshot({ path: testInfo.outputPath('firewall-removal.png') })
	await page.getByRole('button', { name: 'Refresh observed rules' }).click()
	await expect(sshRule).toHaveCount(0)
	await page.getByRole('button', { name: 'Undo', exact: true }).click()
	await expect(sshRule).toBeVisible()
	await expect(
		page.getByRole('button', { name: 'Apply changes', exact: true }),
	).toBeDisabled()
	await removeSSH(page)
	await page.keyboard.press('ControlOrMeta+z')
	await expect(sshRule).toBeVisible()
	await removeSSH(page)
	await discardChanges(page)
	await expect(sshRule).toBeVisible()
})

test('Mod+Z leaves text undo to the field being typed in', async ({ page }) => {
	await openControls(page)
	await page.goto('/tests/server-controls.html?specificFirewall=1')
	const httpsRule = page.getByRole('button', { name: 'Remove HTTPS rule' })
	await httpsRule.click()
	const address = page.getByRole('textbox', {
		name: 'Add an IP address or range, rule 1',
		exact: true,
	})
	await address.fill('203.0.113.9')
	await address.press('ControlOrMeta+z')
	await expect(httpsRule).toHaveCount(0)
})

test('removal reaches the API only after review and Apply', async ({
	page,
}) => {
	await openControls(page)
	await removeSSH(page)
	await page.getByRole('button', { name: 'Apply changes', exact: true }).click()
	await expect(
		page.getByText('No rule allows SSH', { exact: false }),
	).toBeVisible()
	const request = page.waitForRequest(
		'**/central.api.servers.update_server_firewall',
	)
	await page
		.getByRole('button', { name: 'Apply changes', exact: true })
		.last()
		.click()
	const payload = (await request).postDataJSON()
	expect(
		payload.firewall.inbound.map((rule: { ports: string }) => rule.ports),
	).toEqual(['443'])
})

test('resize controls fit a narrow screen', async ({ page }, testInfo) => {
	await page.setViewportSize({ width: 390, height: 844 })
	await openControls(page)
	await openResize(page)
	await expect(
		page.getByRole('radio', { name: 'Keep current 25 GB disk size' }),
	).toBeVisible()
	await page.getByRole('button', { name: /0.125 vCPU/ }).click()
	await page
		.getByRole('button', { name: 'Resize', exact: true })
		.scrollIntoViewIfNeeded()
	await expect(
		page.getByRole('button', { name: 'Resize', exact: true }),
	).toBeInViewport()
	expect(
		await page.evaluate(
			() => document.documentElement.scrollWidth <= window.innerWidth,
		),
	).toBe(true)
	await page.screenshot({ path: testInfo.outputPath('resize-mobile.png') })
})

test('specific addresses replace unrestricted access and invalid ranges stay in the row', async ({
	page,
}, testInfo) => {
	await openControls(page)
	await page
		.getByRole('combobox', { name: 'Allowed from, rule 2', exact: true })
		.click()
	await page
		.getByRole('option', { name: 'Specific addresses', exact: true })
		.click()
	const input = page.getByRole('textbox', {
		name: 'Add an IP address or range, rule 2',
		exact: true,
	})
	await input.fill('999.1.1.1')
	await page.getByRole('button', { name: 'Add', exact: true }).click()
	await expect(page.getByText('Enter a valid IPv4 address.')).toBeVisible()
	await input.fill('203.0.113.7')
	await input.press('Enter')
	await expect(
		page.getByRole('button', { name: 'Remove 203.0.113.7/32', exact: true }),
	).toBeVisible()
	await page.screenshot({ path: testInfo.outputPath('firewall-addresses.png') })
	const request = page.waitForRequest(
		'**/central.api.servers.update_server_firewall',
	)
	await page.getByRole('button', { name: 'Apply changes', exact: true }).click()
	expect(
		(await request)
			.postDataJSON()
			.firewall.inbound.find((rule: { ports: string }) => rule.ports === '443')
			.cidrs,
	).toEqual(['203.0.113.7/32'])
})

test('address validation accepts IPv4 and IPv6 and rejects malformed or non-network ranges', async ({
	page,
}) => {
	await openControls(page)
	const errors = await page.evaluate(async () => {
		const modulePath = '/src/lib/firewall.ts'
		const { getCidrError } = await import(modulePath)
		return [
			'203.0.113.7',
			'203.0.113.0/24',
			'2001:db8::1',
			'2001:db8::/64',
			'999.1.1.1',
			'203.0.113.7/24',
			'2001:db8::1/64',
			'2001:db8::/129',
			'hello',
		].map((value) => !!getCidrError(value))
	})
	expect(errors).toEqual([
		false,
		false,
		false,
		false,
		true,
		true,
		true,
		true,
		true,
	])
})

test('trial resizing preserves the catalog spending exemption', async ({
	page,
}) => {
	await openControls(page, 0, false, false)
	await openResize(page)
	const small = page.getByRole('button', { name: /0.125 vCPU/ })
	await expect(small).toBeEnabled()
	await small.click()
	await expect(
		page.getByRole('button', { name: 'Resize', exact: true }),
	).toBeEnabled()
})

test('enabling an empty firewall applies the complete web defaults together', async ({
	page,
}) => {
	await openControls(page)
	await page.goto('/tests/server-controls.html?emptyFirewall=1')
	await expect(
		page.getByRole('button', { name: 'Add incoming rule', exact: true }),
	).toHaveCount(0)
	const request = page.waitForRequest(
		'**/central.api.servers.update_server_firewall',
	)
	await page.getByRole('switch', { name: 'Firewall', exact: true }).click()
	const { firewall } = (await request).postDataJSON()
	expect(firewall).toEqual({
		enabled: true,
		inbound: ['22', '80', '443'].map((ports) => ({
			protocol: 'tcp',
			ports,
			cidrs: ['0.0.0.0/0', '::/0'],
		})),
		outbound: [{ protocol: 'any', ports: '', cidrs: ['0.0.0.0/0', '::/0'] }],
	})
})

test('new rules show guidance without an empty error or empty address picker', async ({
	page,
}) => {
	await openControls(page)
	await page
		.getByRole('button', { name: 'Add incoming rule', exact: true })
		.click()
	await page
		.getByRole('combobox', { name: 'Service, rule 3', exact: true })
		.click()
	await page.getByRole('option', { name: 'Custom TCP', exact: true }).click()
	await expect(
		page.getByRole('textbox', {
			name: 'Add an IP address or range, rule 3',
			exact: true,
		}),
	).toBeVisible()
	await expect(page.getByRole('alert')).toHaveCount(0)
	await expect(
		page.getByText('Use a port from 1 to 65535, or a range such as 8000-8100.'),
	).toHaveCount(0)
	await expect(
		page.getByRole('button', { name: 'Apply changes', exact: true }),
	).toBeDisabled()
})

test('background observations preserve an address still being typed', async ({
	page,
}) => {
	await openControls(page)
	await page.goto('/tests/server-controls.html?specificFirewall=1')
	const input = page.getByRole('textbox', {
		name: 'Add an IP address or range, rule 1',
		exact: true,
	})
	await input.fill('203.0.113.8')
	await page
		.getByRole('button', { name: 'Refresh observed rules', exact: true })
		.click()
	await expect(input).toHaveValue('203.0.113.8')
})

test('resize option failure shows a retry and cannot submit', async ({
	page,
}) => {
	await openControls(page)
	await page.route(
		'**/central.billing.api.dashboard.catalog.get_composed_config**',
		(route) =>
			route.fulfill({
				status: 500,
				json: { errors: [{ message: 'Resize options unavailable' }] },
			}),
	)
	await page.getByRole('button', { name: 'Resize server', exact: true }).click()
	await expect(
		page.getByText("Couldn't load resize options", { exact: true }),
	).toBeVisible()
	await expect(
		page.getByRole('button', { name: 'Retry', exact: true }),
	).toBeVisible()
	await expect(
		page.getByRole('button', { name: 'Resize', exact: true }),
	).toHaveCount(0)
	await page.unroute(
		'**/central.billing.api.dashboard.catalog.get_composed_config**',
	)
	await page.getByRole('button', { name: 'Retry', exact: true }).click()
	await expect(
		page.getByRole('button', { name: 'Resize', exact: true }),
	).toBeVisible()
	await expect(
		page.getByText("Couldn't load resize options", { exact: true }),
	).toHaveCount(0)
})

test('changed observations block an older draft until reset', async ({
	page,
}) => {
	await openControls(page)
	await page
		.getByRole('button', { name: 'Remove HTTPS rule', exact: true })
		.click()
	await page
		.getByRole('button', { name: 'Remove observed SSH', exact: true })
		.click()
	await expect(
		page.getByText(/The saved firewall rules changed while you were editing/),
	).toBeVisible()
	await expect(
		page.getByRole('button', { name: 'Apply changes', exact: true }),
	).toBeDisabled()
	await discardChanges(page)
	await expect(
		page.getByRole('button', { name: 'Remove SSH rule', exact: true }),
	).toHaveCount(0)
	await expect(
		page.getByRole('button', { name: 'Remove HTTPS rule', exact: true }),
	).toBeVisible()
})

test('empty saved TCP ports do not block unrelated edits', async ({ page }) => {
	await openControls(page)
	await page.goto('/tests/server-controls.html?allTcpPorts=1')
	await page
		.getByRole('button', { name: 'Remove HTTPS rule', exact: true })
		.click()
	await expect(
		page.getByRole('button', { name: 'Apply changes', exact: true }),
	).toBeEnabled()
})

test('custom ports stay editable through preset port prefixes', async ({
	page,
}) => {
	await openControls(page)
	await page
		.getByRole('combobox', { name: 'Service, rule 1', exact: true })
		.first()
		.click()
	await page.getByRole('option', { name: 'Custom TCP', exact: true }).click()
	const port = page
		.getByRole('textbox', { name: 'Port, rule 1', exact: true })
		.first()
	await port.pressSequentially('2200-2205')
	await expect(port).toBeEnabled()
	await expect(port).toHaveValue('2200-2205')
	await expect(
		page
			.getByRole('combobox', { name: 'Service, rule 1', exact: true })
			.first(),
	).toHaveValue('Custom TCP')
})

test('changed observations also block an open Apply confirmation', async ({
	page,
}) => {
	await openControls(page)
	await removeSSH(page)
	await page.getByRole('button', { name: 'Apply changes', exact: true }).click()
	await page
		.getByRole('button', {
			name: 'Remove observed SSH',
			exact: true,
			includeHidden: true,
		})
		.dispatchEvent('click')
	const writes: string[] = []
	page.on('request', (request) => {
		if (request.url().includes('update_server_firewall'))
			writes.push(request.url())
	})
	await page
		.getByRole('dialog')
		.getByRole('button', { name: 'Apply changes', exact: true })
		.click()
	await expect(
		page
			.getByRole('dialog')
			.getByText(/The saved firewall rules changed while you were editing/),
	).toBeVisible()
	expect(writes).toEqual([])
})

test('plan labels show custom sizes and retain named plans and prices', async ({
	page,
}) => {
	await openControls(page)
	const labels = await page.evaluate(async () => {
		const modulePath = '/src/lib/planLabel.ts'
		const { formatPlanLabel } = await import(modulePath)
		return [
			formatPlanLabel({
				vcpus: 2,
				memoryMegabytes: 4096,
				rate: 950,
				currency: 'INR',
			}),
			formatPlanLabel({ vcpus: 0.5, memoryMegabytes: 512 }),
			formatPlanLabel({
				title: 'Starter · 2 vCPU',
				rate: 120,
				currency: 'USD',
				billingCycle: 'Annual',
			}),
			formatPlanLabel({}),
		]
	})
	expect(labels).toEqual([
		'2 vCPU × 4 GB RAM · ₹950/mo',
		'0.5 vCPU × 512 MB RAM',
		'Starter · $120/yr',
		'Custom configuration',
	])
})
