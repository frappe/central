import type { TeamSSHKey as TeamSSHKeyDoc } from './Infrastructure/TeamSSHKey'

/** The fields returned by Central's team SSH key list and create APIs. */
export type TeamSSHKey = Required<
	Pick<TeamSSHKeyDoc, 'name' | 'title' | 'public_key' | 'fingerprint'>
> &
	Pick<TeamSSHKeyDoc, 'last_sync_error'> & {
		server_count: number
	}
