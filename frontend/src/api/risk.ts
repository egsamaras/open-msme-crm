import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, unwrap, type Schemas } from './client'

export type Signal = Schemas['EwsListItem']

export function useSignals(state: 'open' | 'resolved') {
  return useQuery({
    queryKey: ['ews', state],
    queryFn: async () => unwrap(await api.GET('/api/ews', { params: { query: { state } } })),
    placeholderData: keepPreviousData,
  })
}

export function useUpdateSignal(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: Schemas['EwsUpdate']) =>
      unwrap(await api.PATCH('/api/ews/{signal_id}', { params: { path: { signal_id: id } }, body })),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['ews'] })
      void qc.invalidateQueries({ queryKey: ['accounts'] })
    },
  })
}

export function useStartScan() {
  return useMutation({ mutationFn: async () => unwrap(await api.POST('/api/agents/ews-scan')) })
}

/** The per-company review runs a scan started. Polls until none is still running. */
export function useChildRuns(parentId: string | null) {
  return useQuery({
    queryKey: ['agent-runs', 'children', parentId],
    queryFn: async () =>
      unwrap(await api.GET('/api/agent-runs', { params: { query: { parent_run_id: parentId! } } })),
    enabled: parentId !== null,
    refetchInterval: (q) => (q.state.data?.some((r) => r.status === 'RUNNING') ? 1000 : false),
  })
}
