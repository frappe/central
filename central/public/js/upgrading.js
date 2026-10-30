;(() => {
	const page = document.getElementById('page')
	const byId = (id) => document.getElementById(id)

	const STEPS = ['saving', 'moving', 'starting']
	const TERMINAL = ['ready', 'failed', 'invalid']
	const TITLES = {
		ready: 'Your site is ready',
		failed: 'The upgrade did not finish',
		invalid: 'This link is not valid',
	}
	const ANNOUNCEMENTS = {
		saving: 'Saving your new plan',
		moving: 'Moving to a bigger server',
		starting: 'Starting your site',
		ready: 'Your site is ready',
		failed: 'The upgrade did not finish',
		invalid: 'This link is not valid',
	}
	const TAB_TITLES = {
		saving: 'Upgrading (1 of 3)',
		moving: 'Upgrading (2 of 3)',
		starting: 'Upgrading (3 of 3)',
		ready: '✓ Your site is ready',
		failed: 'Upgrade did not finish',
		invalid: 'Link not valid',
	}
	const FLIGHT_STATUS = { saving: 'Boarding', moving: 'In flight', starting: 'Landing', ready: 'Arrived' }
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
		byId('title').textContent = TITLES[progress.step] || 'Upgrading your site'
		byId('lead').textContent = getLead(progress)
	}

	function getLead(progress) {
		if (progress.step === 'failed') return 'We could not move your site to the new plan.'
		if (progress.step === 'invalid') return "Open the upgrade again from your site's settings."
		if (!progress.shape) return 'Your site is moving to its new plan.'
		if (progress.step === 'ready') return `${progress.site} now runs with ${describeCapacity(progress.shape)}.`
		return `${getChanges(previousShape, progress.shape)} Your site goes offline for a few minutes while it moves. Keep this tab open and we open your site when it is ready.`
	}

	// "Memory goes from 1 GB to 2 GB.", naming only what the plan change alters.
	function getChanges(from, to) {
		if (!from) return `Your site moves to ${describeCapacity(to)}.`
		const changes = [
			['CPU', `${formatNumber(from.vcpus)} vCPU`, `${formatNumber(to.vcpus)} vCPU`],
			['memory', formatMemory(from), formatMemory(to)],
			['disk', `${formatNumber(from.disk_gigabytes)} GB`, `${formatNumber(to.disk_gigabytes)} GB`],
		]
			.filter(([, before, after]) => before !== after)
			.map(([part, before, after]) => `${part} goes from ${before} to ${after}`)
		if (!changes.length) return 'Your site keeps its size on the new plan.'
		const sentence = new Intl.ListFormat('en', { type: 'conjunction' }).format(changes)
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
			item.querySelector('.step-state').textContent = state === 'done' ? ', done' : state === 'current' ? ', in progress' : ''
		}
	}

	function renderOutcome(progress) {
		const step = progress.step
		const notice = byId('notice')
		notice.hidden = step !== 'failed'
		if (step === 'failed') {
			const heading = Object.assign(document.createElement('strong'), { textContent: 'Upgrade stopped. ' })
			notice.replaceChildren(heading, progress.error || 'Your site should open on its current plan. If it does not, contact support.')
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
			byId('countdown').textContent = `Taking you there in ${seconds} ${seconds === 1 ? 'second' : 'seconds'}`
			if (seconds-- > 0) return
			stopCountdown()
			if (isPreview) byId('countdown').textContent = 'Preview: this would open your site now.'
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
		byId('elapsed').textContent = `${minutes}:${seconds} elapsed`
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
		return `${formatNumber(shape.vcpus)} vCPU${separator}${formatMemory(shape)}`
	}

	function describeCapacity(shape) {
		return `${formatNumber(shape.vcpus)} vCPU and ${formatMemory(shape)} memory`
	}

	// A plan titled after its size, such as "0.5 vCPU / 1 GB", adds nothing below the size.
	function getPlanDetail(plan, shape) {
		const normalize = (text) => text.toLowerCase().replace(/[^0-9a-z.]/g, '')
		return plan && normalize(plan) !== normalize(describeShape(shape)) ? `${plan} plan` : ''
	}

	function formatMemory(shape) {
		return `${formatNumber(shape.memory_megabytes / 1024)} GB`
	}

	function formatNumber(value) {
		return new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(value)
	}

	function clamp(value, minimum, maximum) {
		return Math.min(Math.max(value, minimum), maximum)
	}

	byId('stay').addEventListener('click', () => {
		stopCountdown()
		byId('countdown').textContent = 'You can open your site when you are ready.'
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
