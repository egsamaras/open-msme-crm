import { useQuery } from '@tanstack/react-query'
import { api, unwrap } from '@/api/client'

export function useAccounts(q: string) {
  return useQuery({
    queryKey: ['accounts', { q }],
    queryFn: async () =>
      unwrap(await api.GET('/api/accounts', { params: { query: q ? { q } : {} } })),
    placeholderData: (prev) => prev,
  })
}
