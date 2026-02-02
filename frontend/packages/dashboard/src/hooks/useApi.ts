import { useContext } from 'react'
import { ApiContext } from '../providers/ApiProvider'

/**
 * Hook to access the API client from context.
 *
 * Usage in pages:
 * ```tsx
 * import { useApi } from '@beadhub/dashboard'
 * import type { ApiClient } from '@beadhub/dashboard'
 *
 * function MyPage() {
 *   const api = useApi<ApiClient>()
 *   // api is strongly typed
 * }
 * ```
 */
export function useApi<T = unknown>(): T {
  const api = useContext(ApiContext)
  if (!api) {
    throw new Error('useApi must be used within an ApiProvider')
  }
  return api as T
}
