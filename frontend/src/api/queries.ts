import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, unwrap, type Schemas } from './client'

export type AccountDetail = Schemas['AccountDetail']
export type Facility = Schemas['FacilityOut']
export type Snapshot = Schemas['SnapshotOut']
export type DocumentRow = Schemas['DocumentOut']
export type InteractionRow = Schemas['InteractionOut']
export type InteractionIn = Schemas['InteractionIn']
export type Task = Schemas['TaskOut']
export type TaskIn = Schemas['TaskIn']
export type Deal = Schemas['DealOut']
export type DealDetail = Schemas['DealDetail']
export type DealPatch = Schemas['DealPatch']
export type DealStage = Deal['stage']
export type Ews = Schemas['EwsOut']

const path = (id: string) => ({ params: { path: { company_id: id } } })

export function useAccount(id: string) {
  return useQuery({
    queryKey: ['accounts', id],
    queryFn: async () => unwrap(await api.GET('/api/accounts/{company_id}', path(id))),
  })
}

export function useFacilities(id: string) {
  return useQuery({
    queryKey: ['accounts', id, 'facilities'],
    queryFn: async () => unwrap(await api.GET('/api/accounts/{company_id}/facilities', path(id))),
  })
}

export function useFinancials(id: string) {
  return useQuery({
    queryKey: ['accounts', id, 'financials'],
    queryFn: async () => unwrap(await api.GET('/api/accounts/{company_id}/financials', path(id))),
  })
}

export function useDocuments(id: string) {
  return useQuery({
    queryKey: ['accounts', id, 'documents'],
    queryFn: async () => unwrap(await api.GET('/api/accounts/{company_id}/documents', path(id))),
  })
}

export function useInteractions(id: string) {
  return useQuery({
    queryKey: ['accounts', id, 'interactions'],
    queryFn: async () => unwrap(await api.GET('/api/accounts/{company_id}/interactions', path(id))),
  })
}

export function useAccountEws(id: string) {
  return useQuery({
    queryKey: ['accounts', id, 'ews'],
    queryFn: async () => unwrap(await api.GET('/api/accounts/{company_id}/ews', path(id))),
  })
}

export function useAccountTasks(id: string) {
  return useQuery({
    queryKey: ['tasks', { company: id }],
    queryFn: async () => unwrap(await api.GET('/api/accounts/{company_id}/tasks', path(id))),
  })
}

export function useLogInteraction(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: InteractionIn) =>
      unwrap(await api.POST('/api/accounts/{company_id}/interactions', { ...path(id), body })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['accounts', id, 'interactions'] }),
  })
}

export function useMyTasks() {
  return useQuery({
    queryKey: ['tasks', { mine: true }],
    queryFn: async () => unwrap(await api.GET('/api/tasks', { params: { query: { mine: true } } })),
  })
}

export function useCreateTask() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: TaskIn) => unwrap(await api.POST('/api/tasks', { body })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['tasks'] }),
  })
}

export function useSetTaskStatus() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, status }: { id: string; status: Task['status'] }) =>
      unwrap(await api.PATCH('/api/tasks/{task_id}', { params: { path: { task_id: id } }, body: { status } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['tasks'] }),
  })
}

export function useDeals(companyId?: string) {
  return useQuery({
    queryKey: ['deals', { companyId }],
    queryFn: async () =>
      unwrap(await api.GET('/api/deals', { params: { query: companyId ? { company_id: companyId } : {} } })),
    placeholderData: keepPreviousData,
  })
}

export function useDeal(id: string | null) {
  return useQuery({
    queryKey: ['deals', id],
    queryFn: async () => unwrap(await api.GET('/api/deals/{deal_id}', { params: { path: { deal_id: id! } } })),
    enabled: id !== null,
  })
}

export function useUpdateDeal(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: DealPatch) =>
      unwrap(await api.PATCH('/api/deals/{deal_id}', { params: { path: { deal_id: id } }, body })),
    onSuccess: (deal) => {
      qc.setQueryData(['deals', id], deal)
      void qc.invalidateQueries({ queryKey: ['deals'] })
    },
  })
}
