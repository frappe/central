export type Platform = 'win' | 'mac' | 'linux' | 'unknown'

export function getPlatform(): Platform {
	const ua = navigator.userAgent.toLowerCase()
	if (ua.includes('win')) return 'win'
	if (ua.includes('mac')) return 'mac'
	if (ua.includes('x11') || ua.includes('linux')) return 'linux'
	return 'unknown'
}

export function isMac(): boolean {
	return getPlatform() === 'mac'
}

export function isWindows(): boolean {
	return getPlatform() === 'win'
}

export function isLinux(): boolean {
	return getPlatform() === 'linux'
}
