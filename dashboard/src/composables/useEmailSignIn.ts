import { API } from '@/api/methods'
import { useProduct } from '@/composables/useProduct'
import { methodUrl, postFrappe } from '@/lib/auth'

/** A new email has no account until a name arrives with its code. */
export type VerifyCodeResponse = { user: string } | { needs_name: true }

// One door for sign-in and signup: every email gets a code, and a new email
// becomes an account when its code is verified. The product only labels the
// signup funnel.
export function useEmailSignIn() {
	const { productKey } = useProduct()
	const product = () => productKey.value || undefined

	async function sendCode(email: string, fullName?: string): Promise<void> {
		await postFrappe(methodUrl(API.sendCode), {
			email,
			full_name: fullName,
			product: product(),
		})
	}

	async function verifyCode(
		email: string,
		code: string,
		fullName?: string,
	): Promise<VerifyCodeResponse> {
		return postFrappe<VerifyCodeResponse>(methodUrl(API.verifyCode), {
			email,
			code,
			full_name: fullName,
			product: product(),
		})
	}

	return { sendCode, verifyCode }
}
