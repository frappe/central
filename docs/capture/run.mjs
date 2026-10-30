import { mkdir, readdir } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { BASE_URL, VIEWPORT, openApp, settle, visit } from './browser.mjs'
import { frameImage, writeWebp } from './frame.mjs'
import { Studio } from './studio.mjs'

const directory = path.dirname(fileURLToPath(import.meta.url))
const MEDIA = path.resolve(directory, '../content/public/media')
const THEMES = ['light', 'dark']
// Space kept around a cropped element, in CSS pixels.
const CROP_MARGIN = 16

/**
 * Captures every scene in `scenes/` for both themes.
 *
 *   node capture/run.mjs                 all scenes
 *   node capture/run.mjs servers/create  scenes whose name contains the filter
 */
async function main() {
	const filter = process.argv[2] ?? ''
	const scenes = (await loadScenes()).filter((scene) => scene.name.includes(filter))
	if (!scenes.length) throw new Error(`No scene matches "${filter}".`)

	for (const theme of THEMES) {
		for (const app of ['console', 'pilot']) {
			const shots = scenes.filter((scene) => getApp(scene) === app && !scene.steps)
			if (shots.length) await captureShots(shots, theme, app)
		}
		for (const clip of scenes.filter((scene) => scene.steps)) await captureClip(clip, theme)
	}
}

async function loadScenes() {
	const files = (await readdir(path.join(directory, 'scenes'))).filter((file) => file.endsWith('.mjs')).sort()
	const modules = await Promise.all(files.map((file) => import(path.join(directory, 'scenes', file))))
	return modules.flatMap((module) => module.default)
}

async function captureShots(scenes, theme, app) {
	const { browser, context, page } = await openApp(theme, { app })
	const data = app === 'console' ? await getConsoleData(context) : {}

	for (const scene of scenes) {
		try {
			await visit(page, resolvePath(scene, data), app)
			if (scene.setup) await scene.setup(page, data)
			await settle(page)

			const image = await page.screenshot({ clip: await getClip(page, scene), animations: 'disabled' })
			await writeMedia(scene.name, theme, 'webp', await frameImage(image, theme))
			console.log(`${theme} ${scene.name}`)
		} catch (error) {
			// One broken scene should not stop the rest. The run still fails at the end.
			console.error(`${theme} ${scene.name} failed: ${error.message.split('\n')[0]}`)
			process.exitCode = 1
		}
	}
	await browser.close()
}

async function captureClip(scene, theme) {
	const app = getApp(scene)
	const { browser, context, page } = await openApp(theme, { app, motion: true })
	await Studio.prepare(context)
	const data = app === 'console' ? await getConsoleData(context) : {}

	await visit(page, resolvePath(scene, data), app)
	if (scene.setup) await scene.setup(page, data)
	const studio = new Studio(page)
	await studio.start()
	await scene.steps(studio, page, data)
	await studio.stop()
	await browser.close()

	const output = path.join(MEDIA, theme, scene.name)
	await mkdir(path.dirname(output), { recursive: true })
	await studio.render(output, theme)
	console.log(`${theme} ${scene.name} (clip)`)
}

/** Reads what scenes refer to by name: the team and a server ID for each server title. */
async function getConsoleData(context) {
	const read = async (method, query = '') => (await (await context.request.get(`${BASE_URL}/api/v2/method/${method}${query}`)).json()).data
	const [team] = await read('central.api.identity.my_teams')
	const registry = await read('central.api.servers.registry', `?team=${team.name}`)
	const servers = Object.fromEntries(registry.servers.map((server) => [server.title, server.resource_id]))
	return { team, servers }
}

/** A scene captures the Frappe Cloud console unless it sets `app: 'pilot'`. */
function getApp(scene) {
	return scene.app ?? 'console'
}

function resolvePath(scene, data) {
	return typeof scene.path === 'function' ? scene.path(data) : scene.path
}

/** The viewport, or a target element with a margin, clamped to the viewport. */
async function getClip(page, scene) {
	if (!scene.target) return { x: 0, y: 0, ...VIEWPORT }

	const locator = typeof scene.target === 'function' ? scene.target(page) : page.locator(scene.target)
	const box = await locator.first().boundingBox()
	if (!box) throw new Error(`${scene.name}: target ${scene.target} is not visible.`)
	const x = Math.max(0, box.x - CROP_MARGIN)
	const y = Math.max(0, box.y - CROP_MARGIN)
	return {
		x,
		y,
		width: Math.min(VIEWPORT.width - x, box.width + CROP_MARGIN * 2),
		height: Math.min(VIEWPORT.height - y, box.height + CROP_MARGIN * 2),
	}
}

async function writeMedia(name, theme, extension, buffer) {
	const file = path.join(MEDIA, theme, `${name}.${extension}`)
	await mkdir(path.dirname(file), { recursive: true })
	await writeWebp(buffer, file)
}

await main()
