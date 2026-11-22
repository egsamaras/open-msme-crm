import createClient from 'openapi-fetch'
import type { components, paths } from './schema'

/** Typed API client. Types are generated from the backend: `npm run generate:api`. */
export const api = createClient<paths>({
  baseUrl: globalThis.location?.origin ?? '',
  credentials: 'include',
  // Look fetch up at call time (not import time) so tests can stub it.
  fetch: (request) => globalThis.fetch(request),
})

export type Schemas = components['schemas']
export type User = Schemas['UserOut']
export type AccountListItem = Schemas['AccountListItem']
export type Role = User['role']

export class ApiError extends Error {
  readonly status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

/** Unwrap an openapi-fetch result, throwing ApiError on failure. */
export function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (result.error !== undefined || result.data === undefined) {
    const detail = (result.error as { detail?: unknown } | undefined)?.detail
    const message = typeof detail === 'string' ? detail : `Request failed (${result.response.status})`
    throw new ApiError(result.response.status, message)
  }
  return result.data
}
