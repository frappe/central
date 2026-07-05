import { computed, ref, watch } from 'vue'
import { useRoute, useRouter, type LocationQueryRaw } from 'vue-router'
import { emailError, frappeErrorMessage, postFrappe, queryString, requiredError } from '@/lib/auth'
import { loadCountryData, type CountryOption } from '@/lib/countries'

// Shared state + submit for both signup layouts (plain and ?product=).
export function useSignup() {
  const route = useRoute()
  const router = useRouter()
  const fullName = ref('')
  const email = ref('')
  const submitted = ref(false)
  const loading = ref(false)
  const error = ref('')

  // UI-only for now: sign_up doesn't accept a country yet.
  const country = ref('')
  const countries = ref<CountryOption[]>([])
  loadCountryData()
    .then((data) => {
      countries.value = data.options
      country.value ||= data.defaultCountry
    })
    // Country is UI-only, so a failed load just leaves an empty dropdown — don't block signup.
    .catch(() => {})

  // A server error describes the last attempt; drop it once the user edits the form.
  watch([fullName, email], () => {
    error.value = ''
  })

  const product = computed(() => queryString(route.query.product))
  const isProductSignup = computed(() => Boolean(product.value))

  async function signup() {
    submitted.value = true
    error.value = ''
    if (requiredError('Full name')(fullName.value) || emailError(email.value)) return

    loading.value = true
    try {
      const response = await postFrappe<[number, string]>(
        '/api/method/central.api.auth.sign_up',
        {
          full_name: fullName.value.trim(),
          email: email.value.trim(),
        },
      )
      const [status, message] = response ?? [0, 'Unable to create your account.']
      if (status !== 1) {
        error.value = message
        return
      }
      await router.push({ path: '/signup/verify', query: verificationQuery() })
    } catch (exception) {
      error.value = frappeErrorMessage(exception, 'Unable to create your account.')
    } finally {
      loading.value = false
    }
  }

  function verificationQuery(): LocationQueryRaw {
    return {
      email: email.value.trim(),
      ...(product.value ? { product: product.value } : {}),
    }
  }

  return { fullName, email, country, countries, submitted, loading, error, product, isProductSignup, signup }
}
