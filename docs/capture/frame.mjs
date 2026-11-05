import sharp from 'sharp'

/** One frame style for every screenshot and video, in CSS pixels, so all media share padding, radius, and shadow. */
const FRAME = {
	padding: 28,
	radius: 10,
	shadowBlur: 14,
	shadowOffset: 5,
}

function getFrame(density) {
	return Object.fromEntries(Object.entries(FRAME).map(([key, value]) => [key, Math.round(value * density)]))
}

// Soft gradients from the Espresso gray scale, one per theme.
const BACKGROUNDS = {
	light: { from: '#F8F8F8', to: '#E9EDF2', glow: '#FFFFFF', shadow: 'rgba(15, 23, 42, 0.16)', edge: 'rgba(0, 0, 0, 0.08)' },
	dark: { from: '#1C1C1C', to: '#101010', glow: '#2A2A2A', shadow: 'rgba(0, 0, 0, 0.55)', edge: 'rgba(255, 255, 255, 0.10)' },
}

export function getBackgroundSvg(theme, width, height) {
	const colors = BACKGROUNDS[theme]
	return Buffer.from(`<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}">
		<defs>
			<linearGradient id="base" x1="0" y1="0" x2="1" y2="1">
				<stop offset="0" stop-color="${colors.from}"/><stop offset="1" stop-color="${colors.to}"/>
			</linearGradient>
			<radialGradient id="glow" cx="0.2" cy="0" r="0.9">
				<stop offset="0" stop-color="${colors.glow}" stop-opacity="0.9"/><stop offset="1" stop-color="${colors.glow}" stop-opacity="0"/>
			</radialGradient>
		</defs>
		<rect width="100%" height="100%" fill="url(#base)"/>
		<rect width="100%" height="100%" fill="url(#glow)"/>
	</svg>`)
}

function getShadowSvg(theme, width, height, frame) {
	const { padding, radius, shadowBlur, shadowOffset } = frame
	const outerWidth = width + padding * 2
	const outerHeight = height + padding * 2
	return Buffer.from(`<svg xmlns="http://www.w3.org/2000/svg" width="${outerWidth}" height="${outerHeight}">
		<filter id="blur"><feGaussianBlur stdDeviation="${shadowBlur / 2}"/></filter>
		<rect x="${padding}" y="${padding + shadowOffset}" width="${width}" height="${height}" rx="${radius}" fill="${BACKGROUNDS[theme].shadow}" filter="url(#blur)"/>
	</svg>`)
}

function getEdgeSvg(theme, width, height, { radius }) {
	return Buffer.from(`<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}">
		<rect x="0.5" y="0.5" width="${width - 1}" height="${height - 1}" rx="${radius}" fill="none" stroke="${BACKGROUNDS[theme].edge}"/>
	</svg>`)
}

function getMaskSvg(width, height, { radius }) {
	return Buffer.from(`<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}">
		<rect width="${width}" height="${height}" rx="${radius}" fill="#fff"/>
	</svg>`)
}

/** Places a raw capture on the themed background with rounded corners, an edge line, and a shadow. */
export async function frameImage(input, theme, density = 2) {
	const { width, height } = await sharp(input).metadata()
	const frame = getFrame(density)
	const { padding } = frame

	const rounded = await sharp(input)
		.composite([
			{ input: getMaskSvg(width, height, frame), blend: 'dest-in' },
			{ input: getEdgeSvg(theme, width, height, frame) },
		])
		.png()
		.toBuffer()

	return sharp(getBackgroundSvg(theme, width + padding * 2, height + padding * 2))
		.composite([{ input: getShadowSvg(theme, width, height, frame) }, { input: rounded, left: padding, top: padding }])
		.png()
		.toBuffer()
}

export async function writeWebp(buffer, path) {
	await sharp(buffer).webp({ quality: 90, effort: 5 }).toFile(path)
}
