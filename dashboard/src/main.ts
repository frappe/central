import { loadTranslations } from '@/lib/translate'
import './style.css'

// A module may call __() when it loads, so the app loads only after the catalog.
loadTranslations().then(() => import('@/app'))
