import { createAvatar } from '@dicebear/core'
import { notionists } from '@dicebear/collection'
import sharp from 'sharp'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const directory = path.dirname(fileURLToPath(import.meta.url))

const PEOPLE = {
	zara: { seed: 'Zara Quill', backgroundColor: ['ffd5dc'] },
	kofi: { seed: 'Kofi Brightwater', backgroundColor: ['c0e8ff'] },
	ines: { seed: 'Ines Marlowe', backgroundColor: ['d1f4d9'] },
	otis: { seed: 'Otis Penny', backgroundColor: ['ffe8b3'] },
	bea: { seed: 'Bea Lockhart', backgroundColor: ['e3d7ff'] },
	juniper: { seed: 'Juniper Hale', backgroundColor: ['ffdfbf'] },
	rafa: { seed: 'Rafa Ozturk', backgroundColor: ['b6e3f4'] },
	nova: { seed: 'Nova Achebe', backgroundColor: ['d1d4f9'] },
	teddy: { seed: 'Teddy Zhou', backgroundColor: ['c0f0e8'] },
}

for (const [name, options] of Object.entries(PEOPLE)) {
	const svg = createAvatar(notionists, { ...options, size: 256 }).toString()
	await sharp(Buffer.from(svg)).png().toFile(path.join(directory, `${name}.png`))
}
