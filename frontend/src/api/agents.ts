import { keepPreviousData, useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api, unwrap, type Schemas } from './client'

export type Approval = Schemas['ApprovalOut']
export type AgentRun = Schemas['AgentRunDetail']
export type AgentRunSummary = Schemas['AgentRunSummary']
export type AuditEvent = Schemas['AuditEventOut']
export type TraceEvent = Record<string, unknown> & { type: string; at: string }

export function useApprovals(state: 'pending' | 'resolved') {
  return useQuery({
    queryKey: ['approvals', state],
    queryFn: async () => unwrap(await api.GET('/api/approvals', { params: { query: { state } } })),
    placeholderData: keepPreviousData,
  })
}

export function useApprovalCount() {
  return useQuery({
    queryKey: ['approvals', 'count'],
    queryFn: async () => unwrap(await api.GET('/api/approvals/count')),
    refetchInterval: 30_000,
  })
}

export function useResolveApproval(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: Schemas['ResolveIn']) =>
      unwrap(await api.POST('/api/approvals/{approval_id}/resolve', { params: { path: { approval_id: id } }, body })),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['approvals'] })
      void qc.invalidateQueries({ queryKey: ['tasks'] })
      void qc.invalidateQueries({ queryKey: ['agent-runs'] })
      // Approved actions change alerts, deals, owners and documents.
      for (const key of ['ews', 'deals', 'accounts']) void qc.invalidateQueries({ queryKey: [key] })
    },
  })
}

export function useAgentRun(id: string | null) {
  return useQuery({
    queryKey: ['agent-runs', id],
    queryFn: async () => unwrap(await api.GET('/api/agent-runs/{run_id}', { params: { path: { run_id: id! } } })),
    enabled: id !== null,
  })
}

export function useStartBriefing(companyId: string) {
  return useMutation({
    mutationFn: async () =>
      unwrap(await api.POST('/api/agents/briefing/{company_id}', { params: { path: { company_id: companyId } } })),
  })
}

export function useStartDemoAgent(companyId: string) {
  return useMutation({
    mutationFn: async () =>
      unwrap(await api.POST('/api/dev/agents/demo-followup/{company_id}', { params: { path: { company_id: companyId } } })),
  })
}

/** Live trace of a run via Server-Sent Events. Stops when the run pauses or finishes. */
export function useRunStream(runId: string | null) {
  const qc = useQueryClient()
  // State is tagged with its run id, so a new run starts empty without resetting state in the effect.
  const [stream, setStream] = useState<{ runId: string; events: TraceEvent[]; status: string | null }>()
  useEffect(() => {
    if (!runId) return
    const source = new EventSource(`/api/agent-runs/${runId}/stream`, { withCredentials: true })
    const update = (fn: (s: { events: TraceEvent[]; status: string | null }) => { events: TraceEvent[]; status: string | null }) =>
      setStream((prev) => ({ runId, ...fn(prev?.runId === runId ? prev : { events: [], status: null }) }))
    source.addEventListener('trace', (e) =>
      update((s) => ({ ...s, events: [...s.events, JSON.parse((e as MessageEvent).data) as TraceEvent] })),
    )
    source.addEventListener('status', (e) => {
      const status = (JSON.parse((e as MessageEvent).data) as { status: string }).status
      update((s) => ({ ...s, status }))
      source.close()
      void qc.invalidateQueries({ queryKey: ['approvals'] })
    })
    source.addEventListener('error', () => {
      update((s) => ({ ...s, status: s.status ?? 'FAILED' }))
      source.close()
    })
    return () => source.close()
  }, [runId, qc])
  const current = stream?.runId === runId ? stream : undefined
  return { events: current?.events ?? [], status: runId ? (current?.status ?? 'RUNNING') : null }
}

export function useAuditEvents() {
  return useInfiniteQuery({
    queryKey: ['audit', 'events'],
    initialPageParam: undefined as number | undefined,
    queryFn: async ({ pageParam }) =>
      unwrap(await api.GET('/api/audit/events', { params: { query: { limit: 50, ...(pageParam ? { before_seq: pageParam } : {}) } } })),
    getNextPageParam: (last) => (last.length === 50 ? last[last.length - 1]!.seq : undefined),
  })
}

export function useAuditVerify() {
  return useQuery({
    queryKey: ['audit', 'verify'],
    queryFn: async () => unwrap(await api.GET('/api/audit/verify')),
  })
}
