import type { LocationQuery } from 'vue-router'
import { useRouter } from 'vue-router'
import { API } from '@/api/methods'
import { useAuth } from '@/composables/useAuth'
import { useProduct } from '@/composables/useProduct'
import { useSession } from '@/composables/useSession'
import { methodUrl, postFrappe } from '@/lib/auth'
import { productOnboarding, signInDestination } from '@/lib/authRedirect'

export type SignedIn = { user: string; csrf_token: string }

/** A new email has no account until a name arrives with its code. */
export type VerifyCodeResponse = SignedIn | { needs_name: true }

// One door for sign-in and signup: every email gets a code, and a new email
// becomes an account when its code is verified. The product only labels the
// signup funnel.
export function useEmailSignIn() {
	const { productKey } = useProduct()
	const { enterSession } = useAuth()
	const { reload: reloadTeams } = useSession()
	const router = useRouter()
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

	// A product signup goes on in place. Anywhere else, or after a failed start, a full load boots the console.
	async function enterConsole(
		signedIn: SignedIn,
		query: LocationQuery,
	): Promise<void> {
		const destination = signInDestination(query)
		const onboarding = productOnboarding(query)
		if (!onboarding) return window.location.replace(destination)

		enterSession(signedIn.user, signedIn.csrf_token)
		try {
			await reloadTeams()
			await router.replace(onboarding)
		} catch {
			window.location.replace(destination)
		}
	}

	return { sendCode, verifyCode, enterConsole }
}
