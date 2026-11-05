export type FirewallProtocol = 'any' | 'tcp' | 'udp' | 'icmp'

/** One allow rule, in the form Atlas stores it. */
export interface FirewallRule {
	protocol: FirewallProtocol
	ports: string
	cidrs: string[]
}

/** The customer's rules. Central adds its own rules for the private network, VPN and ping. */
export interface FirewallRules {
	inbound: FirewallRule[]
	outbound: FirewallRule[]
}

export interface FirewallService {
	label: string
	protocol: FirewallProtocol
	/** The fixed port, or null when the person types one. */
	ports: string | null
}

export const ANYWHERE_IPV4 = '0.0.0.0/0'
export const ANYWHERE_IPV6 = '::/0'
/** The region's private network: the web console, the regional proxy and the team's servers. */
export const PRIVATE_NETWORK = 'fdaa::/16'
/** Every WireGuard VPN device of every team in the region. */
export const WIREGUARD_NETWORK = 'fdac::/16'

export const SERVICES: FirewallService[] = [
	{ label: 'SSH', protocol: 'tcp', ports: '22' },
	{ label: 'HTTP', protocol: 'tcp', ports: '80' },
	{ label: 'HTTPS', protocol: 'tcp', ports: '443' },
	{ label: 'MariaDB', protocol: 'tcp', ports: '3306' },
	{ label: 'PostgreSQL', protocol: 'tcp', ports: '5432' },
	{ label: 'Redis', protocol: 'tcp', ports: '6379' },
	{ label: 'Ping', protocol: 'icmp', ports: '' },
	{ label: 'Custom TCP', protocol: 'tcp', ports: null },
	{ label: 'Custom UDP', protocol: 'udp', ports: null },
	{ label: 'All traffic', protocol: 'any', ports: '' },
]

/** The customer's firewall: its state and its rules. */
export type Firewall = FirewallRules & { enabled: boolean }

/** A change to a firewall. A field left out keeps its saved value. */
export type FirewallChange = Partial<Firewall>

const ANYWHERE = [ANYWHERE_IPV4, ANYWHERE_IPV6]
const ALL_OUTBOUND: FirewallRule[] = [
	{ protocol: 'any', ports: '', cidrs: ANYWHERE },
]
// Every new server starts with these. They are ordinary rules that the customer can remove.
const DEFAULT_INBOUND: FirewallRule[] = [
	{ protocol: 'any', ports: '', cidrs: [PRIVATE_NETWORK] },
	{ protocol: 'icmp', ports: '', cidrs: ANYWHERE },
]
const allow = (...ports: string[]): FirewallRule[] => [
	...DEFAULT_INBOUND,
	...ports.map((port) => ({
		protocol: 'tcp' as const,
		ports: port,
		cidrs: ANYWHERE,
	})),
]

/** Starting rule sets. Each one keeps the private network and ping, and lets the server reach the internet. */
export const PRESETS: { label: string; rules: FirewallRules }[] = [
	{
		label: 'Web server',
		rules: { inbound: allow('22', '80', '443'), outbound: ALL_OUTBOUND },
	},
	{
		label: 'SSH only',
		rules: { inbound: allow('22'), outbound: ALL_OUTBOUND },
	},
	{
		label: 'Private only',
		rules: { inbound: allow(), outbound: ALL_OUTBOUND },
	},
]

export function getService(rule: FirewallRule): FirewallService {
	return (
		SERVICES.find(
			(service) =>
				service.protocol === rule.protocol && service.ports === rule.ports,
		) ??
		SERVICES.find(
			(service) => service.protocol === rule.protocol && service.ports === null,
		) ??
		SERVICES[SERVICES.length - 1]
	)
}

export function getPortLabel(rule: FirewallRule): string {
	if (rule.protocol === 'any') return 'All'
	if (rule.protocol === 'icmp') return 'ICMP'
	return `${rule.protocol.toUpperCase()} ${rule.ports || 'all'}`
}

/** A readable name for an address range. `names` maps a device address to its name. */
export function getAddressLabel(
	cidr: string,
	names: Record<string, string> = {},
): string {
	if (cidr === ANYWHERE_IPV4) return 'Anywhere (IPv4)'
	if (cidr === ANYWHERE_IPV6) return 'Anywhere (IPv6)'
	if (cidr === PRIVATE_NETWORK) return 'Private network'
	if (cidr === WIREGUARD_NETWORK) return 'All WireGuard VPN devices'
	return names[cidr] ?? cidr
}

// The web console and the regional proxy use more than one port, so only All traffic keeps them.
const allowsPrivateNetwork = (rules: FirewallRule[]): boolean =>
	rules.some(
		(rule) =>
			rule.protocol === 'any' &&
			rule.cidrs.some((cidr) =>
				[PRIVATE_NETWORK, ANYWHERE_IPV6].includes(cidr),
			),
	)

/** An enabled firewall lets WireGuard VPN devices in only through a rule that names them. */
export function isBlockingWireGuard(
	isEnabled: boolean,
	inbound: FirewallRule[],
): boolean {
	if (!isEnabled) return false
	return !inbound.some(
		(rule) =>
			rule.protocol !== 'icmp' &&
			rule.cidrs.some(
				(cidr) => cidr === ANYWHERE_IPV6 || cidr.startsWith('fdac:'),
			),
	)
}

/** A single address becomes a one-address range, the form Atlas stores. */
export function toCidr(value: string): string {
	const address = value.trim()
	if (!address || address.includes('/')) return address
	return address.includes(':') ? `${address}/128` : `${address}/32`
}

/** Empty TCP/UDP ports allow all ports, as in Central's firewall contract. */
export function isValidPortRange(ports: string): boolean {
	if (!ports) return true
	// Match one positive integer or two separated by a hyphen, without leading zeros.
	// Capture the start and optional end; numeric checks enforce order and the port limit.
	const match = /^([1-9]\d*)(?:-([1-9]\d*))?$/.exec(ports)
	if (!match) return false
	const start = Number(match[1])
	const end = Number(match[2] ?? match[1])
	return start <= end && end <= 65535
}

export function getRuleError(rule: FirewallRule): string {
	if (!rule.cidrs.length)
		return `Choose an address for ${getService(rule).label}.`
	if (['tcp', 'udp'].includes(rule.protocol) && !isValidPortRange(rule.ports))
		return 'Enter a port from 1 to 65535, an ascending range, or leave it empty for all ports.'
	return ''
}

export function getRulesError(rules: FirewallRule[]): string {
	for (const [index, rule] of rules.entries()) {
		const error = getRuleError(rule)
		if (error) return error
		if (rules.slice(index + 1).some((other) => isSameRule(rule, other)))
			return 'Two rules are identical. Remove one before applying.'
	}
	return ''
}

export function isSameRules(a: FirewallRules, b: FirewallRules): boolean {
	return (['inbound', 'outbound'] as const).every(
		(direction) =>
			a[direction].length === b[direction].length &&
			a[direction].every((rule, index) =>
				isSameRule(rule, b[direction][index]),
			),
	)
}

interface AddressBits {
	bits: bigint | null
	error: string
}

function parseIpv4(address: string): AddressBits {
	const parts = address.split('.')
	if (
		parts.length !== 4 ||
		parts.some((part) => !/^(0|[1-9]\d{0,2})$/.test(part) || Number(part) > 255)
	)
		return { bits: null, error: 'Enter a valid IPv4 address.' }
	return {
		bits: parts.reduce((result, part) => (result << 8n) + BigInt(part), 0n),
		error: '',
	}
}

function parseIpv6(address: string, mask: number): AddressBits {
	let canonical: string
	try {
		canonical = new URL(`http://[${address}]/`).hostname.slice(1, -1)
	} catch {
		return { bits: null, error: 'Enter a valid IPv6 address.' }
	}
	if (canonical !== address)
		return { bits: null, error: `Use ${canonical}/${mask} for this address.` }
	const [left, right] = canonical
		.split('::')
		.map((part) => (part ? part.split(':') : []))
	const groups = right
		? [...left, ...Array(8 - left.length - right.length).fill('0'), ...right]
		: left
	return {
		bits: BigInt(`0x${groups.map((part) => part.padStart(4, '0')).join('')}`),
		error: '',
	}
}

function getPrefixError(prefix: string, width: number): string {
	const mask = Number(prefix)
	if (mask > width) return `The range prefix must be between 0 and ${width}.`
	if (String(mask) !== prefix)
		return 'Use a range prefix without leading zeros.'
	return ''
}

function hasValidCidrParts(
	address: string,
	prefix: string | undefined,
	extra: string | undefined,
): boolean {
	return !!address && /^\d+$/.test(prefix ?? '') && extra === undefined
}

/** Check an address before adding it; Central validates the complete change again. */
export function getCidrError(value: string): string {
	const [address, prefix, extra] = toCidr(value).split('/')
	if (!hasValidCidrParts(address, prefix, extra))
		return 'Enter an IP address or a range, such as 203.0.113.7 or 203.0.113.0/24.'
	const width = address.includes(':') ? 128 : 32
	const prefixError = getPrefixError(prefix, width)
	if (prefixError) return prefixError
	const mask = Number(prefix)
	const parsed = width === 128 ? parseIpv6(address, mask) : parseIpv4(address)
	if (parsed.bits === null) return parsed.error
	const hostMask = (1n << BigInt(width - mask)) - 1n
	if (parsed.bits & hostMask)
		return 'Use the network address for a range, such as 203.0.113.0/24.'
	return ''
}

export function isSameRule(a: FirewallRule, b: FirewallRule): boolean {
	return (
		a.protocol === b.protocol &&
		a.ports === b.ports &&
		[...a.cidrs].sort().join() === [...b.cidrs].sort().join()
	)
}

function opensSSH(rules: FirewallRule[]): boolean {
	return rules.some(
		(rule) =>
			rule.protocol === 'any' ||
			(rule.protocol === 'tcp' && (rule.ports === '22' || rule.ports === '')),
	)
}

/** What stops working when a firewall changes from `before` to `after`. */
export function getFirewallTexts(before: Firewall, after: Firewall): string[] {
	if (!after.enabled)
		return before.enabled ? ['Every port will be open to the internet.'] : []

	const warnings: string[] = []
	const hasPrivate = allowsPrivateNetwork(after.inbound)
	if (!hasPrivate && (!before.enabled || allowsPrivateNetwork(before.inbound)))
		warnings.push(
			"No rule allows the private network, so the web console, the regional proxy and your other servers can't reach this server. Sites stop loading through the proxy.",
		)
	const allowsPing = (rules: FirewallRule[]) =>
		rules.some(
			(rule) =>
				['icmp', 'any'].includes(rule.protocol) &&
				rule.cidrs.includes(ANYWHERE_IPV6),
		)
	if (
		!allowsPing(after.inbound) &&
		(!before.enabled || allowsPing(before.inbound))
	)
		warnings.push('No rule allows ping, so some IPv6 connections can fail.')
	if (!opensSSH(after.inbound) && (!before.enabled || opensSSH(before.inbound)))
		warnings.push(
			hasPrivate
				? 'No rule allows SSH, so SSH connections will stop. The web console still works.'
				: 'No rule allows SSH, so SSH connections will stop.',
		)
	if (!after.outbound.length && (!before.enabled || before.outbound.length))
		warnings.push(
			"No outgoing rule, so the server can't install updates or send email.",
		)
	return warnings
}
