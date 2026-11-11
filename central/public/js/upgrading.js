;(() => {
	const page = document.getElementById('page')
	const byId = (id) => document.getElementById(id)
	const translations = JSON.parse(page.dataset.translations || '{}')
	// Frappe's __: the translation of a literal, with {0}, {1} filled from `values`.
	const __ = (text, values = []) => (translations[text] || text).replace(/\{(\d+)\}/g, (match, index) => values[index] ?? match)

	const STEPS = ['saving', 'moving', 'starting']
	const TERMINAL = ['ready', 'failed', 'invalid']
	const TITLES = {
		ready: __('Your site is ready'),
		failed: __('The upgrade did not finish'),
		invalid: __('This link is not valid'),
	}
	const ANNOUNCEMENTS = {
		saving: __('Saving your new plan'),
		moving: __('Moving to a bigger server'),
		starting: __('Starting your site'),
		ready: __('Your site is ready'),
		failed: __('The upgrade did not finish'),
		invalid: __('This link is not valid'),
	}
	const TAB_TITLES = {
		saving: __('Upgrading ({0} of {1})', [1, 3]),
		moving: __('Upgrading ({0} of {1})', [2, 3]),
		starting: __('Upgrading ({0} of {1})', [3, 3]),
		ready: `✓ ${__('Your site is ready')}`,
		failed: __('Upgrade did not finish'),
		invalid: __('Link not valid'),
	}
	const FLIGHT_STATUS = { saving: __('Boarding'), moving: __('In flight'), starting: __('Landing'), ready: __('Arrived') }
	const POLL_MILLISECONDS = 3000
	const REDIRECT_SECONDS = 5
	// Map units of the dotted world asset, and the strip shown around the region.
	const MAP = { width: 879, height: 443, latitudeTop: 83, latitudeBottom: -56, stripWidth: 200, stripHeight: 74 }

	const isPreview = page.dataset.preview === '1'
	let current = null
	// The server reports its old plan and size until the resize lands; keep the first ones seen.
	let previousPlan = null
	let previousShape = null
	let elapsedSeconds = 0
	let countdownTimer = null

	function render(progress) {
		const step = progress.step
		const hasChanged = !current || current.step !== step
		current = progress
		page.dataset.step = step
		previousPlan = previousPlan || progress.current_plan
		previousShape = previousShape || progress.current_shape

		renderHeader(progress)
		renderTicket(progress)
		renderMap(progress)
		renderSteps(step)
		renderOutcome(progress)

		document.title = TAB_TITLES[step]
		if (hasChanged) byId('announce').textContent = ANNOUNCEMENTS[step]
	}

	function renderHeader(progress) {
		const host = progress.site || ''
		byId('site-name').textContent = host
		byId('monogram').textContent = host.charAt(0).toUpperCase()
		byId('title').textContent = TITLES[progress.step] || __('Upgrading your site')
		byId('lead').textContent = getLead(progress)
	}

	function getLead(progress) {
		if (progress.step === 'failed') return __('We could not move your site to the new plan.')
		if (progress.step === 'invalid') return __("Open the upgrade again from your site's settings.")
		if (!progress.shape) return __('Your site is moving to its new plan.')
		if (progress.step === 'ready') return __('{0} now runs with {1}.', [progress.site, describeCapacity(progress.shape)])
		return __('{0} Your site goes offline for a few minutes while it moves. Keep this tab open and we open your site when it is ready.', [
			getChanges(previousShape, progress.shape),
		])
	}

	// "Memory goes from 1 GB to 2 GB.", naming only what the plan change alters.
	function getChanges(from, to) {
		if (!from) return __('Your site moves to {0}.', [describeCapacity(to)])
		const changes = [
			[__('CPU goes from {0} to {1}'), formatCPU(from), formatCPU(to)],
			[__('memory goes from {0} to {1}'), formatMemory(from), formatMemory(to)],
			[__('disk goes from {0} to {1}'), formatDisk(from), formatDisk(to)],
		]
			.filter(([, before, after]) => before !== after)
			.map(([template, before, after]) => template.replace('{0}', before).replace('{1}', after))
		if (!changes.length) return __('Your site keeps its size on the new plan.')
		const sentence = new Intl.ListFormat(document.documentElement.lang || 'en', { type: 'conjunction' }).format(changes)
		return `${sentence.charAt(0).toUpperCase()}${sentence.slice(1)}.`
	}

	// The ticket is in the page once; only its data changes, so the plane glides between steps.
	function renderTicket(progress) {
		const shape = progress.shape
		byId('capacity').hidden = !shape || !(progress.step in FLIGHT_STATUS)
		if (!shape) return

		const from = previousShape || shape
		byId('from-plan').textContent = describeShape(from, '\n')
		byId('from-shape').textContent = getPlanDetail(previousPlan, from)
		byId('to-plan').textContent = describeShape(shape, '\n')
		byId('to-shape').textContent = getPlanDetail(progress.plan, shape)
		byId('ticket-site').textContent = progress.site
		byId('ticket-region').textContent = (progress.region && progress.region.display_name) || '—'
		byId('ticket-status').textContent = FLIGHT_STATUS[progress.step] || ''

		const ticket = byId('ticket')
		ticket.dataset.step = progress.step
		// The first placement is instant; later steps glide.
		requestAnimationFrame(() => ticket.classList.add('is-animated'))
	}

	function renderMap(progress) {
		const region = progress.region
		const hasPoint = region && region.latitude != null && region.longitude != null && !(region.latitude === 0 && region.longitude === 0)
		byId('map').hidden = !hasPoint || progress.step === 'invalid'
		if (!hasPoint) return

		const x = ((region.longitude + 180) / 360) * MAP.width
		const y = ((MAP.latitudeTop - region.latitude) / (MAP.latitudeTop - MAP.latitudeBottom)) * MAP.height
		const left = clamp(x - MAP.stripWidth / 2, 0, MAP.width - MAP.stripWidth)
		const top = clamp(y - MAP.stripHeight / 2, 0, MAP.height - MAP.stripHeight)
		byId('map-svg').setAttribute('viewBox', `${left} ${top} ${MAP.stripWidth} ${MAP.stripHeight}`)
		byId('pin').setAttribute('transform', `translate(${x} ${y})`)
		byId('map-label').textContent = region.display_name
	}

	function renderSteps(step) {
		const list = byId('steps')
		list.hidden = step === 'failed' || step === 'invalid'
		const reached = step === 'ready' ? STEPS.length : STEPS.indexOf(step)
		for (const item of list.children) {
			const index = STEPS.indexOf(item.dataset.step)
			const state = index < reached ? 'done' : index === reached ? 'current' : 'pending'
			item.dataset.state = state
			item.querySelector('.step-state').textContent = state === 'done' ? `, ${__('done')}` : state === 'current' ? `, ${__('in progress')}` : ''
		}
	}

	function renderOutcome(progress) {
		const step = progress.step
		const notice = byId('notice')
		notice.hidden = step !== 'failed'
		if (step === 'failed') {
			const heading = Object.assign(document.createElement('strong'), { textContent: `${__('Upgrade stopped.')} ` })
			notice.replaceChildren(heading, progress.error || __('Your site should open on its current plan. If it does not, contact support.'))
		}

		byId('foot').hidden = TERMINAL.includes(step)
		byId('actions').hidden = !(step === 'ready' || step === 'failed')
		byId('go').href = progress.site_url || '#'
		if (step === 'ready') startCountdown()
		else stopCountdown()
	}

	function startCountdown() {
		if (countdownTimer) return
		let seconds = REDIRECT_SECONDS
		byId('stay').hidden = false
		const tick = () => {
			byId('countdown').textContent = seconds === 1 ? __('Taking you there in 1 second') : __('Taking you there in {0} seconds', [seconds])
			if (seconds-- > 0) return
			stopCountdown()
			if (isPreview) byId('countdown').textContent = __('Preview: this would open your site now.')
			else window.location.assign(current.site_url)
		}
		tick()
		countdownTimer = window.setInterval(tick, 1000)
	}

	function stopCountdown() {
		window.clearInterval(countdownTimer)
		countdownTimer = null
		byId('stay').hidden = true
		byId('countdown').textContent = ''
	}

	function tickElapsed() {
		elapsedSeconds += 1
		const minutes = Math.floor(elapsedSeconds / 60)
		const seconds = String(elapsedSeconds % 60).padStart(2, '0')
		byId('elapsed').textContent = __('{0} elapsed', [`${minutes}:${seconds}`])
	}

	async function poll() {
		try {
			const response = await fetch(`/api/method/central.api.sites.plan_change_progress?${page.dataset.query}`, {
				headers: { Accept: 'application/json' },
			})
			if (response.status === 403 || response.status === 404) return render({ step: 'invalid' })
			if (response.ok) {
				const progress = (await response.json()).message
				elapsedSeconds = progress.elapsed_seconds
				render(progress)
			}
		} catch {
			// A dropped request is retried on the next poll; the page keeps its last state.
		}
		if (!TERMINAL.includes(current.step)) window.setTimeout(poll, POLL_MILLISECONDS)
	}

	function describeShape(shape, separator = ' · ') {
		return `${formatCPU(shape)}${separator}${formatMemory(shape)}`
	}

	function describeCapacity(shape) {
		return __('{0} and {1} memory', [formatCPU(shape), formatMemory(shape)])
	}

	// A plan titled after its size, such as "0.5 vCPU / 1 GB", adds nothing below the size.
	function getPlanDetail(plan, shape) {
		const normalize = (text) => text.toLowerCase().replace(/[^0-9a-z.]/g, '')
		return plan && normalize(plan) !== normalize(describeShape(shape)) ? __('{0} plan', [plan]) : ''
	}

	function formatCPU(shape) {
		return __('{0} vCPU', [formatNumber(shape.vcpus)])
	}

	function formatMemory(shape) {
		return __('{0} GB', [formatNumber(shape.memory_megabytes / 1024)])
	}

	function formatDisk(shape) {
		return __('{0} GB', [formatNumber(shape.disk_gigabytes)])
	}

	function formatNumber(value) {
		return new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(value)
	}

	function clamp(value, minimum, maximum) {
		return Math.min(Math.max(value, minimum), maximum)
	}

	byId('stay').addEventListener('click', () => {
		stopCountdown()
		byId('countdown').textContent = __('You can open your site when you are ready.')
	})

	window.setInterval(tickElapsed, 1000)

	if (isPreview) startPreview()
	else if (page.dataset.progress) {
		const progress = JSON.parse(page.dataset.progress)
		elapsedSeconds = progress.elapsed_seconds
		render(progress)
		if (!TERMINAL.includes(progress.step)) window.setTimeout(poll, POLL_MILLISECONDS)
	} else render({ step: 'invalid' })

	function startPreview() {
		const sample = {
			site: 'acme.frappe.cloud',
			site_url: '#',
			plan: 'Pro',
			current_plan: 'Starter',
			shape: { vcpus: 2, memory_megabytes: 4096, disk_gigabytes: 40 },
			current_shape: { vcpus: 1, memory_megabytes: 2048, disk_gigabytes: 25 },
			region: { display_name: 'Paris', latitude: 48.8566, longitude: 2.3522 },
			error: null,
		}
		const form = byId('preview')
		let playTimer = null
		const show = (step) => {
			form.elements.step.value = step
			render({ ...sample, step })
		}
		form.addEventListener('change', () => {
			window.clearTimeout(playTimer)
			render({ ...sample, step: form.elements.step.value })
		})
		byId('play').addEventListener('click', () => {
			window.clearTimeout(playTimer)
			elapsedSeconds = 0
			const sequence = ['saving', 'moving', 'starting', 'ready']
			const next = (index) => {
				show(sequence[index])
				if (index < sequence.length - 1) playTimer = window.setTimeout(() => next(index + 1), 2500)
			}
			next(0)
		})
		show('saving')
	}
})()
