import { mkdir, rm, writeFile } from 'node:fs/promises'
import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import path from 'node:path'
import sharp from 'sharp'
import ffmpeg from 'ffmpeg-static'
import { VIEWPORT } from './browser.mjs'
import { frameImage } from './frame.mjs'

const run = promisify(execFile)
const FPS = 30
const OUTPUT_WIDTH = 1600
const ZOOM = 1.6
// Camera moves ease over this long, so zooms feel deliberate rather than jumpy.
const CAMERA_SECONDS = 0.7

// A drawn cursor, because a screencast does not include the system pointer.
const CURSOR_SCRIPT = `
addEventListener('DOMContentLoaded', () => {
	const cursor = document.createElement('div')
	cursor.id = 'studio-cursor'
	cursor.innerHTML = '<svg width="22" height="22" viewBox="0 0 24 24"><path d="M5 3l14 8-6 2-3 6z" fill="#111" stroke="#fff" stroke-width="1.5" stroke-linejoin="round"/></svg>'
	Object.assign(cursor.style, { position: 'fixed', left: '-40px', top: '-40px', zIndex: 2147483647, pointerEvents: 'none', transition: 'transform 120ms' })
	document.body.append(cursor)
	addEventListener('mousemove', (event) => { cursor.style.left = event.clientX - 4 + 'px'; cursor.style.top = event.clientY - 3 + 'px' }, true)
	addEventListener('mousedown', (event) => {
		cursor.style.transform = 'scale(0.85)'
		const ripple = document.createElement('div')
		Object.assign(ripple.style, { position: 'fixed', left: event.clientX - 18 + 'px', top: event.clientY - 18 + 'px', width: '36px', height: '36px', borderRadius: '50%', background: 'rgba(59,130,246,0.35)', zIndex: 2147483646, pointerEvents: 'none', transition: 'transform 450ms ease-out, opacity 450ms ease-out' })
		document.body.append(ripple)
		requestAnimationFrame(() => { ripple.style.transform = 'scale(1.8)'; ripple.style.opacity = '0' })
		setTimeout(() => ripple.remove(), 500)
	}, true)
	addEventListener('mouseup', () => { cursor.style.transform = 'scale(1)' }, true)
})`

/** Records one console flow with a moving cursor and a camera that zooms to each action. */
export class Studio {
	constructor(page) {
		this.page = page
		this.frames = []
		this.camera = []
		this.pointer = { x: VIEWPORT.width / 2, y: VIEWPORT.height / 2 }
	}

	static async prepare(context) {
		await context.addInitScript(CURSOR_SCRIPT)
	}

	async start() {
		this.session = await this.page.context().newCDPSession(this.page)
		this.session.on('Page.screencastFrame', async ({ data, metadata, sessionId }) => {
			this.frames.push({ time: metadata.timestamp, data: Buffer.from(data, 'base64') })
			await this.session.send('Page.screencastFrameAck', { sessionId }).catch(() => {})
		})
		await this.session.send('Page.startScreencast', { format: 'jpeg', quality: 92, everyNthFrame: 1 })
		this.startedAt = Date.now() / 1000
		this.focus(null)
		await this.page.mouse.move(this.pointer.x, this.pointer.y)
		await this.wait(600)
	}

	async stop() {
		await this.wait(500)
		await this.session.send('Page.stopScreencast')
		this.stoppedAt = Date.now() / 1000
	}

	/** Zooms the camera to a point in page pixels, or back out to the full page with `null`. */
	focus(point, scale = ZOOM) {
		this.camera.push({ time: Date.now() / 1000, x: point?.x ?? VIEWPORT.width / 2, y: point?.y ?? VIEWPORT.height / 2, scale: point ? scale : 1 })
	}

	async wait(milliseconds) {
		await this.page.waitForTimeout(milliseconds)
	}

	async moveTo(locator) {
		const box = await locator.boundingBox()
		if (!box) throw new Error(`Studio cannot see ${locator}`)
		const target = { x: box.x + box.width / 2, y: box.y + box.height / 2 }
		const distance = Math.hypot(target.x - this.pointer.x, target.y - this.pointer.y)
		const steps = Math.max(12, Math.round(distance / 14))

		for (let step = 1; step <= steps; step++) {
			const progress = easeInOut(step / steps)
			await this.page.mouse.move(this.pointer.x + (target.x - this.pointer.x) * progress, this.pointer.y + (target.y - this.pointer.y) * progress)
			await this.page.waitForTimeout(12)
		}
		this.pointer = target
		return target
	}

	async click(locator, { zoom = true } = {}) {
		const target = await this.moveTo(locator)
		if (zoom) this.focus(target)
		await this.wait(250)
		await this.page.mouse.down()
		await this.page.mouse.up()
		await this.wait(500)
	}

	async type(locator, text) {
		await this.click(locator)
		await this.page.keyboard.type(text, { delay: 70 })
		await this.wait(500)
	}

	async zoomOut() {
		this.focus(null)
		await this.wait(900)
	}

	/** Renders the recording to `<output>.mp4` and a framed poster `<output>.webp`. */
	async render(output, theme) {
		const directory = `${output}.frames`
		await rm(directory, { recursive: true, force: true })
		await mkdir(directory, { recursive: true })

		const duration = this.stoppedAt - this.startedAt
		const count = Math.floor(duration * FPS)
		let frameIndex = 0
		for (let index = 0; index < count; index++) {
			const time = this.startedAt + index / FPS
			while (frameIndex + 1 < this.frames.length && this.frames[frameIndex + 1].time <= time) frameIndex++
			const image = await this.getCameraView(this.frames[frameIndex].data, this.getCamera(time))
			await writeFile(path.join(directory, `${String(index).padStart(5, '0')}.png`), await frameImage(image, theme, OUTPUT_WIDTH / VIEWPORT.width))
		}

		await run(ffmpeg, ['-y', '-loglevel', 'error', '-framerate', String(FPS), '-i', path.join(directory, '%05d.png'), '-c:v', 'libx264', '-preset', 'slow', '-crf', '20', '-pix_fmt', 'yuv420p', '-vf', 'scale=trunc(iw/2)*2:trunc(ih/2)*2', '-movflags', '+faststart', `${output}.mp4`])
		await sharp(path.join(directory, '00000.png')).webp({ quality: 88 }).toFile(`${output}.webp`)
		await rm(directory, { recursive: true, force: true })
	}

	getCamera(time) {
		let current = this.camera[0]
		let previous = current
		for (const keyframe of this.camera) {
			if (keyframe.time > time) break
			previous = current
			current = keyframe
		}
		const progress = easeInOut(Math.min(1, (time - current.time) / CAMERA_SECONDS))
		const mix = (key) => previous[key] + (current[key] - previous[key]) * progress
		return { x: mix('x'), y: mix('y'), scale: mix('scale') }
	}

	async getCameraView(jpeg, camera) {
		const { width, height } = await sharp(jpeg).metadata()
		const ratio = width / VIEWPORT.width
		const cropWidth = Math.round(width / camera.scale)
		const cropHeight = Math.round(height / camera.scale)
		const left = clamp(Math.round(camera.x * ratio - cropWidth / 2), 0, width - cropWidth)
		const top = clamp(Math.round(camera.y * ratio - cropHeight / 2), 0, height - cropHeight)
		return sharp(jpeg).extract({ left, top, width: cropWidth, height: cropHeight }).resize(OUTPUT_WIDTH, Math.round((OUTPUT_WIDTH * VIEWPORT.height) / VIEWPORT.width)).png().toBuffer()
	}
}

function easeInOut(value) {
	return value < 0.5 ? 4 * value ** 3 : 1 - (-2 * value + 2) ** 3 / 2
}

function clamp(value, minimum, maximum) {
	return Math.min(Math.max(value, minimum), maximum)
}
