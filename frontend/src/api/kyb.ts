import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api, unwrap, type Schemas } from './client'

export type DocType = Schemas['DocumentOut']['doc_type']

/** Upload a document (multipart) and start its KYB check. */
export function useUploadDocument(companyId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ docType, file }: { docType: DocType; file: File }) =>
      unwrap(
        await api.POST('/api/documents/upload', {
          body: { company_id: companyId, doc_type: docType, file: file as unknown as string },
          bodySerializer: (body) => {
            const form = new FormData()
            form.append('company_id', body.company_id)
            form.append('doc_type', body.doc_type)
            form.append('file', body.file as unknown as Blob)
            return form
          },
        }),
      ),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['accounts', companyId, 'documents'] }),
  })
}

export function useCheckDocument(companyId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (documentId: string) =>
      unwrap(await api.POST('/api/documents/{document_id}/check', { params: { path: { document_id: documentId } } })),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['accounts', companyId, 'documents'] }),
  })
}
