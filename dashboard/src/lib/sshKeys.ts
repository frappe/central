// Central sends these keys to Atlas as guest metadata, and on a non-Pilot image they are
// the only way in, so a typo becomes a machine nobody can log into. The server parses
// every key properly before it provisions; this is the fast check that keeps a bad paste
// from travelling that far.
const KEY_TYPES = [
	'ssh-ed25519',
	'ssh-rsa',
	'ssh-dss',
	'ecdsa-sha2-nistp256',
	'ecdsa-sha2-nistp384',
	'ecdsa-sha2-nistp521',
	'sk-ssh-ed25519@openssh.com',
	'sk-ecdsa-sha2-nistp256@openssh.com',
]

export function parseSSHKeys(value: string): string[] {
	return value
		.split('\n')
		.map((line) => line.trim())
		.filter(Boolean)
}

/** The reason these keys can't be used, or '' when they can. */
export function sshKeysProblem(value: string): string {
	const lines = parseSSHKeys(value)
	const seen = new Set<string>()

	for (const [index, line] of lines.entries()) {
		const subject = lines.length > 1 ? `Line ${index + 1}` : 'That'
		if (line.startsWith('-----BEGIN'))
			return `${subject} is a private key. Paste the public key instead, the line from your .pub file.`

		const [type, body] = line.split(/\s+/)
		if (!body || !KEY_TYPES.includes(type))
			return `${subject} is not an OpenSSH public key. A key starts with ssh-ed25519 or ssh-rsa.`
		if (keyTypeInside(body) !== type)
			return `${subject} is not a complete ${type} key. Copy the whole line from your .pub file.`
		if (seen.has(body)) return `${subject} repeats a key above.`

		seen.add(body)
	}

	return ''
}

// An OpenSSH key body is base64 of a run of length-prefixed fields, the first being the
// algorithm name. Walking the fields to the exact end catches a paste that was cut short
// or edited, which still looks right from the outside.
function keyTypeInside(body: string): string | null {
	try {
		const blob = Uint8Array.from(atob(body), (character) =>
			character.charCodeAt(0),
		)
		const fields = new DataView(blob.buffer)
		let algorithm = ''
		let offset = 0
		while (offset + 4 <= blob.length) {
			const length = fields.getUint32(offset)
			offset += 4
			if (offset + length > blob.length) return null
			if (!algorithm)
				algorithm = new TextDecoder().decode(
					blob.subarray(offset, offset + length),
				)
			offset += length
		}

		return offset === blob.length ? algorithm : null
	} catch {
		return null
	}
}
