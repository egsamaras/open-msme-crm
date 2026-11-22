import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, unwrap, type User } from '@/api/client'

export const meKey = ['auth', 'me'] as const

/** The signed-in user, or null when signed out. */
export function useMe() {
  return useQuery({
    queryKey: meKey,
    // /session answers 200 with user: null when signed out, so no 401 noise in the console.
    queryFn: async (): Promise<User | null> => unwrap(await api.GET('/api/auth/session')).user ?? null,
    staleTime: 60_000,
  })
}

export function useAppInfo() {
  return useQuery({
    queryKey: ['info'],
    queryFn: async () => unwrap(await api.GET('/api/info')),
    staleTime: Infinity,
  })
}

export function usePersonas(enabled: boolean) {
  return useQuery({
    queryKey: ['auth', 'personas'],
    queryFn: async () => unwrap(await api.GET('/api/auth/personas')),
    enabled,
    staleTime: Infinity,
  })
}

function useSetUser() {
  const qc = useQueryClient()
  return (user: User | null) => {
    // A different user can see different data: drop everything cached, then set the user.
    qc.removeQueries({ predicate: (q) => q.queryKey[0] !== 'info' && q.queryKey[0] !== 'auth' })
    qc.setQueryData(meKey, user)
  }
}

export function useLogin() {
  const setUser = useSetUser()
  return useMutation({
    mutationFn: async (body: { email: string; password: string }) =>
      unwrap(await api.POST('/api/auth/login', { body })),
    onSuccess: setUser,
  })
}

export function useSwitchPersona() {
  const setUser = useSetUser()
  return useMutation({
    mutationFn: async (userId: string) =>
      unwrap(await api.POST('/api/auth/dev-switch', { body: { user_id: userId } })),
    onSuccess: setUser,
  })
}

export function useLogout() {
  const setUser = useSetUser()
  return useMutation({
    mutationFn: async () => {
      await api.POST('/api/auth/logout')
    },
    onSuccess: () => setUser(null),
  })
}
