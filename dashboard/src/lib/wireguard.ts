import type { WireGuardDevice } from '@/types/wireguard'

const toBase64 = (bytes: ArrayBuffer): string =>
	btoa(String.fromCharCode(...new Uint8Array(bytes)))

export const isWireGuardKey = (key: string): boolean =>
	/^[A-Za-z0-9+/]{43}=$/.test(key.trim())

export interface KeyPair {
	privateKey: string
	publicKey: string
}

/** A WireGuard key pair made by the browser. Null when the browser has no X25519. */
export async function generateKeyPair(): Promise<KeyPair | null> {
	try {
		const pair = (await crypto.subtle.generateKey({ name: 'X25519' }, true, [
			'deriveBits',
		])) as CryptoKeyPair
		const [pkcs8, raw] = await Promise.all([
			crypto.subtle.exportKey('pkcs8', pair.privateKey),
			crypto.subtle.exportKey('raw', pair.publicKey),
		])
		// the raw private key is the last 32 bytes of pkcs8
		return { privateKey: toBase64(pkcs8.slice(-32)), publicKey: toBase64(raw) }
	} catch {
		return null
	}
}

export const buildConfig = (
	device: WireGuardDevice,
	privateKey: string,
): string =>
	[
		'[Interface]',
		`PrivateKey = ${privateKey}`,
		`Address = ${device.address}`,
		'',
		'[Peer]',
		`PublicKey = ${device.gateway_public_key}`,
		`AllowedIPs = ${device.allowed_ips.split('\n').join(', ')}`,
		`Endpoint = ${device.endpoint}`,
		'PersistentKeepalive = 25',
		'',
	].join('\n')

/** The customer guide for WireGuard VPN. */
export const WIREGUARD_DOCS_URL =
	'https://frappe.github.io/central/servers/wireguard'

/** Stands in for a private key the browser no longer has. */
export const PRIVATE_KEY_PLACEHOLDER = '<your private key>'

/** wg-quick takes the interface name from the file name, at most 15 characters. */
export function downloadConfig(
	device: WireGuardDevice,
	privateKey: string,
): void {
	const config = buildConfig(device, privateKey || PRIVATE_KEY_PLACEHOLDER)
	const link = document.createElement('a')
	link.href = URL.createObjectURL(new Blob([config], { type: 'text/plain' }))
	const name = device.title
		.toLowerCase()
		.replace(/[^a-z0-9]+/g, '-')
		.slice(0, 15)
		.replace(/^-+|-+$/g, '')
	link.download = `${name || 'wireguard'}.conf`
	link.click()
	URL.revokeObjectURL(link.href)
}
