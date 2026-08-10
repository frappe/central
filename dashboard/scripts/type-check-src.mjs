// Type-check gate scoped to our own code. `vue-tsc --noEmit` also type-checks
// frappe-ui's shipped .vue/.ts source (imported through the graph; skipLibCheck
// only skips .d.ts), which carries pre-existing errors we can't fix. Run it, then
// fail only on diagnostics in our src/ — so the gate guards our code, not the
// library's internals.
import { execFileSync } from 'node:child_process'
import { existsSync } from 'node:fs'

// Invoke the local binary directly: run standalone (`node scripts/...`) the
// node_modules/.bin shims aren't on PATH, and a missing binary must fail the gate
// loudly rather than look green.
const bin = process.platform === 'win32' ? 'vue-tsc.cmd' : 'vue-tsc'
const binPath = `node_modules/.bin/${bin}`
if (!existsSync(binPath)) {
	console.error(`✗ ${binPath} not found — run yarn install first.`)
	process.exit(1)
}

let output = ''
try {
	output = execFileSync(binPath, ['--noEmit', '--pretty', 'false'], {
		encoding: 'utf8',
		stdio: ['ignore', 'pipe', 'pipe'],
	})
} catch (error) {
	// vue-tsc exits non-zero whenever there are any errors (ours or frappe-ui's).
	output = `${error.stdout ?? ''}${error.stderr ?? ''}`
	if (!output.includes('error TS')) {
		console.error('✗ vue-tsc failed to run:\n', output)
		process.exit(1)
	}
}

const ours = output.split('\n').filter((line) => line.startsWith('src/'))
if (ours.length) {
	console.error(ours.join('\n'))
	console.error(`\n✗ ${ours.length} type error(s) in src/`)
	process.exit(1)
}
console.log('✓ No type errors in src/')
