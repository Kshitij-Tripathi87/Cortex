'use client'

import { useState, useEffect, useCallback, useMemo, Suspense } from 'react'
import { useSearchParams } from 'next/navigation'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000/api/v1'

// Types
interface EvidenceClaim {
  claim_id: string
  workspace_id: string
  source_file_id: string
  batch_id: string
  row_number: number
  source_column: string
  canonical_entity: string | null
  canonical_field: string | null
  raw_value: string
  normalized_value: string | null
  confidence: number
  claim_state: string
  requires_review: boolean
  created_at: string
}

interface PaginatedResponse<T> {
  data: T[]
  page: { next_cursor: string | null; prev_cursor: string | null; limit: number; has_more: boolean }
}

// API
async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...options.headers },
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

// Utility
function formatDate(iso: string) { return new Date(iso).toLocaleString() }
function stateColor(state: string) {
  switch (state) {
    case 'accepted': return 'bg-green-100 text-green-800'
    case 'pending_review': return 'bg-yellow-100 text-yellow-800'
    case 'rejected': return 'bg-red-100 text-red-800'
    case 'superseded': return 'bg-gray-100 text-gray-800'
    case 'conflicted': return 'bg-orange-100 text-orange-800'
    default: return 'bg-gray-100 text-gray-800'
  }
}
function formatConfidence(c: number) { return `${(c * 100).toFixed(0)}%` }

function EvidenceContent() {
  const searchParams = useSearchParams()
  const workspaceId = searchParams.get('workspace_id') || 'default-workspace'
  
  const [claims, setClaims] = useState<EvidenceClaim[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  
  // Filters
  const [filters, setFilters] = useState({
    state: '' as string,
    entity: '' as string,
    field: '' as string,
    search: '' as string,
    minConfidence: 0,
    requiresReview: false,
  })
  const [sort, setSort] = useState<{ field: string; dir: 'asc' | 'desc' }>({ field: 'created_at', dir: 'desc' })
  const [pagination, setPagination] = useState({ cursor: null as string | null, pageSize: 50, total: 0 })
  const [selectedClaim, setSelectedClaim] = useState<EvidenceClaim | null>(null)

  // Fetch claims
  const fetchClaims = useCallback(async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams()
      params.set('workspace_id', workspaceId)
      params.set('limit', String(pagination.pageSize))
      if (pagination.cursor) params.set('cursor', pagination.cursor)
      if (filters.state) params.set('state', filters.state)
      if (filters.entity) params.set('entity', filters.entity)
      if (filters.field) params.set('field', filters.field)
      if (filters.search) params.set('q', filters.search)
      if (filters.minConfidence > 0) params.set('min_confidence', String(filters.minConfidence))
      if (filters.requiresReview) params.set('requires_review', 'true')
      params.set('sort', `${sort.field}:${sort.dir}`)
      
      const data = await api<PaginatedResponse<EvidenceClaim>>(`/claims?${params.toString()}`)
      setClaims(data.data)
      setPagination(p => ({ ...p, cursor: data.page.next_cursor, total: data.page.has_more ? (p.total + data.data.length) : p.total }))
    } catch (e: any) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [workspaceId, filters, sort, pagination.cursor, pagination.pageSize])

  useEffect(() => { fetchClaims() }, [fetchClaims])

  // Filtered claims (client-side for instant feedback)
  const filteredClaims = useMemo(() => {
    let result = claims
    if (filters.search) {
      const q = filters.search.toLowerCase()
      result = result.filter(c => 
        c.claim_id.toLowerCase().includes(q) ||
        c.source_column.toLowerCase().includes(q) ||
        c.raw_value.toLowerCase().includes(q) ||
        (c.normalized_value || '').toLowerCase().includes(q) ||
        (c.canonical_entity || '').toLowerCase().includes(q) ||
        (c.canonical_field || '').toLowerCase().includes(q)
      )
    }
    return result
  }, [claims, filters.search])

  // Stats
  const stats = useMemo(() => ({
    total: claims.length,
    pending: claims.filter(c => c.claim_state === 'pending_review').length,
    accepted: claims.filter(c => c.claim_state === 'accepted').length,
    rejected: claims.filter(c => c.claim_state === 'rejected').length,
    conflicting: claims.filter(c => c.claim_state === 'conflicted').length,
    requiresReview: claims.filter(c => c.requires_review).length,
    avgConfidence: claims.length ? claims.reduce((a, c) => a + c.confidence, 0) / claims.length : 0,
  }), [claims])

  return (
    <div className="min-h-screen p-6 bg-gray-50">
      <div className="max-w-full mx-auto">
        {/* Header */}
        <div className="mb-6 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <h1 className="text-3xl font-bold text-gray-900">Evidence Review</h1>
            <p className="text-gray-600 mt-1">Review extracted claims, validate mappings, and approve evidence</p>
          </div>
          <div className="flex gap-3">
            <button className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 text-sm">
              Export CSV
            </button>
            <button className="px-4 py-2 border rounded text-sm text-gray-700 hover:bg-gray-50">
              Bulk Actions
            </button>
          </div>
        </div>

        {/* Stats Bar */}
        <div className="grid grid-cols-2 md:grid-cols-6 gap-4 mb-6">
          <div className="bg-white p-4 rounded-lg shadow-sm border">
            <p className="text-sm text-gray-500">Total Claims</p>
            <p className="text-2xl font-bold text-gray-900">{stats.total.toLocaleString()}</p>
          </div>
          <div className="bg-white p-4 rounded-lg shadow-sm border">
            <p className="text-sm text-gray-500">Pending Review</p>
            <p className="text-2xl font-bold text-yellow-600">{stats.pending.toLocaleString()}</p>
          </div>
          <div className="bg-white p-4 rounded-lg shadow-sm border">
            <p className="text-sm text-gray-500">Accepted</p>
            <p className="text-2xl font-bold text-green-600">{stats.accepted.toLocaleString()}</p>
          </div>
          <div className="bg-white p-4 rounded-lg shadow-sm border">
            <p className="text-sm text-gray-500">Rejected</p>
            <p className="text-2xl font-bold text-red-600">{stats.rejected.toLocaleString()}</p>
          </div>
          <div className="bg-white p-4 rounded-lg shadow-sm border">
            <p className="text-sm text-gray-500">Conflicts</p>
            <p className="text-2xl font-bold text-orange-600">{stats.conflicting.toLocaleString()}</p>
          </div>
          <div className="bg-white p-4 rounded-lg shadow-sm border">
            <p className="text-sm text-gray-500">Avg Confidence</p>
            <p className="text-2xl font-bold text-blue-600">{(stats.avgConfidence * 100).toFixed(1)}%</p>
          </div>
        </div>

        {/* Filters */}
        <div className="bg-white rounded-lg shadow-sm border mb-6 p-4">
          <div className="flex flex-wrap gap-4 items-end">
            {/* Search */}
            <div className="flex-1 min-w-[200px]">
              <label className="block text-sm font-medium mb-1">Search</label>
              <input
                type="text"
                placeholder="Search claim ID, column, value, entity, field…"
                value={filters.search}
                onChange={e => setFilters(f => ({ ...f, search: e.target.value }))}
                className="w-full border rounded px-3 py-2"
              />
            </div>

            {/* State Filter */}
            <div className="min-w-[150px]">
              <label className="block text-sm font-medium mb-1">State</label>
              <select
                value={filters.state}
                onChange={e => setFilters(f => ({ ...f, state: e.target.value }))}
                className="w-full border rounded px-3 py-2"
              >
                <option value="">All States</option>
                <option value="pending_review">Pending Review</option>
                <option value="accepted">Accepted</option>
                <option value="rejected">Rejected</option>
                <option value="superseded">Superseded</option>
                <option value="conflicted">Conflicted</option>
              </select>
            </div>

            {/* Entity Filter */}
            <div className="min-w-[150px]">
              <label className="block text-sm font-medium mb-1">Entity</label>
              <select
                value={filters.entity}
                onChange={e => setFilters(f => ({ ...f, entity: e.target.value }))}
                className="w-full border rounded px-3 py-2"
              >
                <option value="">All Entities</option>
                <option value="Supplier">Supplier</option>
                <option value="Product">Product</option>
                <option value="Facility">Facility</option>
                <option value="PurchaseOrder">Purchase Order</option>
                <option value="Shipment">Shipment</option>
                <option value="Route">Route</option>
              </select>
            </div>

            {/* Confidence */}
            <div className="min-w-[150px]">
              <label className="block text-sm font-medium mb-1">Min Confidence</label>
              <input
                type="range"
                min="0"
                max="100"
                value={filters.minConfidence}
                onChange={e => setFilters(f => ({ ...f, minConfidence: Number(e.target.value) }))}
                className="w-full"
              />
              <span className="text-sm text-gray-500">{filters.minConfidence}%</span>
            </div>

            {/* Requires Review */}
            <div className="flex items-end">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={filters.requiresReview}
                  onChange={e => setFilters(f => ({ ...f, requiresReview: e.target.checked }))}
                  className="rounded"
                />
                <span className="text-sm">Requires Review Only</span>
              </label>
            </div>

            {/* Clear Filters */}
            <button
              onClick={() => setFilters({
                state: '', entity: '', field: '', search: '', minConfidence: 0, requiresReview: false
              })}
              className="text-sm text-blue-600 hover:text-blue-800 self-end mb-1"
            >
              Clear All Filters
            </button>
          </div>
        </div>

        {/* Claims Table */}
        <div className="bg-white rounded-lg shadow-sm border">
          {loading && claims.length === 0 ? (
            <div className="p-8 text-center text-gray-500">Loading claims…</div>
          ) : error ? (
            <div className="p-4 text-red-600">{error}</div>
          ) : filteredClaims.length === 0 ? (
            <div className="p-8 text-center text-gray-500">
              No claims match the current filters.
              <button onClick={() => setFilters({ state: '', entity: '', field: '', search: '', minConfidence: 0, requiresReview: false })}
                className="ml-2 text-blue-600 hover:underline"
              >
                Clear filters
              </button>
            </div>
          ) : (
            <>
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead className="bg-gray-50 sticky top-0 z-10">
                    <tr className="text-left text-sm text-gray-500">
                      <th className="px-4 py-3 cursor-pointer" onClick={() => setSort(f => f.field === 'claim_id' ? { field: 'claim_id', dir: f.dir === 'asc' ? 'desc' : 'asc' } : { field: 'claim_id', dir: 'asc' })}>
                        Claim ID {sort.field === 'claim_id' ? (sort.dir === 'asc' ? '↑' : '↓') : ''}
                      </th>
                      <th className="px-4 py-3 cursor-pointer" onClick={() => setSort(f => f.field === 'source_column' ? { field: 'source_column', dir: f.dir === 'asc' ? 'desc' : 'asc' } : { field: 'source_column', dir: 'asc' })}>
                        Source Column {sort.field === 'source_column' ? (sort.dir === 'asc' ? '↑' : '↓') : ''}
                      </th>
                      <th className="px-4 py-3 cursor-pointer" onClick={() => setSort(f => f.field === 'canonical_entity' ? { field: 'canonical_entity', dir: f.dir === 'asc' ? 'desc' : 'asc' } : { field: 'canonical_entity', dir: 'asc' })}>
                        Entity {sort.field === 'canonical_entity' ? (sort.dir === 'asc' ? '↑' : '↓') : ''}
                      </th>
                      <th className="px-4 py-3 cursor-pointer" onClick={() => setSort(f => f.field === 'canonical_field' ? { field: 'canonical_field', dir: f.dir === 'asc' ? 'desc' : 'asc' } : { field: 'canonical_field', dir: 'asc' })}>
                        Field {sort.field === 'canonical_field' ? (sort.dir === 'asc' ? '↑' : '↓') : ''}
                      </th>
                      <th className="px-4 py-3">Raw Value</th>
                      <th className="px-4 py-3">Normalized</th>
                      <th className="px-4 py-3 cursor-pointer" onClick={() => setSort(f => f.field === 'confidence' ? { field: 'confidence', dir: f.dir === 'asc' ? 'desc' : 'asc' } : { field: 'confidence', dir: 'asc' })}>
                        Confidence {sort.field === 'confidence' ? (sort.dir === 'asc' ? '↑' : '↓') : ''}
                      </th>
                      <th className="px-4 py-3 cursor-pointer" onClick={() => setSort(f => f.field === 'claim_state' ? { field: 'claim_state', dir: f.dir === 'asc' ? 'desc' : 'asc' } : { field: 'claim_state', dir: 'asc' })}>
                        State {sort.field === 'claim_state' ? (sort.dir === 'asc' ? '↑' : '↓') : ''}
                      </th>
                      <th className="px-4 py-3">Review</th>
                      <th className="px-4 py-3">Created</th>
                      <th className="px-4 py-3">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-200">
                    {filteredClaims.map(claim => (
                      <tr key={claim.claim_id} className="hover:bg-gray-50">
                        <td className="px-4 py-3 text-sm font-mono text-gray-500">{claim.claim_id.slice(0, 12)}…</td>
                        <td className="px-4 py-3 text-sm text-gray-600">{claim.source_column}</td>
                        <td className="px-4 py-3 text-sm text-gray-900">{claim.canonical_entity || '—'}</td>
                        <td className="px-4 py-3 text-sm text-gray-600">{claim.canonical_field || '—'}</td>
                        <td className="px-4 py-3 text-sm font-mono text-gray-600 max-w-xs truncate">{claim.raw_value}</td>
                        <td className="px-4 py-3 text-sm text-gray-600 max-w-xs truncate">{claim.normalized_value || '—'}</td>
                        <td className="px-4 py-3 text-sm">
                          <div className="flex items-center gap-2">
                            <div className="w-20 h-2 bg-gray-200 rounded overflow-hidden">
                              <div className="h-full bg-green-500" style={{ width: `${claim.confidence * 100}%` }} />
                            </div>
                            <span className="text-xs">{(claim.confidence * 100).toFixed(0)}%</span>
                          </div>
                        </td>
                        <td className="px-4 py-3">
                          <span className={`px-2 py-1 text-xs rounded ${stateColor(claim.claim_state)}`}>
                            {claim.claim_state.replace('_', ' ')}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-center">
                          {claim.requires_review ? (
                            <span className="px-2 py-1 text-xs bg-yellow-100 text-yellow-800 rounded">Review</span>
                          ) : (
                            <span className="text-gray-400">—</span>
                          )}
                        </td>
                        <td className="px-4 py-3 text-sm text-gray-500">{formatDate(claim.created_at)}</td>
                        <td className="px-4 py-3">
                          <div className="flex gap-2">
                            <button
                              onClick={() => setSelectedClaim(claim)}
                              className="text-sm text-blue-600 hover:text-blue-800"
                            >
                              View
                            </button>
                            {claim.claim_state === 'pending_review' && (
                              <>
                                <button className="text-sm text-green-600 hover:text-green-800">Accept</button>
                                <button className="text-sm text-red-600 hover:text-red-800">Reject</button>
                              </>
                            )}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Pagination */}
              <div className="p-4 border-t flex justify-between items-center text-sm text-gray-500">
                <span>
                  Showing {claims.length} of {pagination.total + claims.length} claims
                </span>
                <div className="flex gap-2">
                  <button
                    className="px-3 py-1 border rounded disabled:opacity-50"
                    disabled={!pagination.cursor}
                    onClick={() => setPagination(p => ({ ...p, cursor: null }))}
                  >
                    First
                  </button>
                  <button
                    className="px-3 py-1 border rounded disabled:opacity-50"
                    disabled={!pagination.cursor}
                    onClick={() => setPagination(p => ({ ...p, cursor: null }))}
                  >
                    Previous
                  </button>
                  <button
                    className="px-3 py-1 border rounded disabled:opacity-50"
                    disabled={!pagination.cursor}
                    onClick={() => setPagination(p => ({ ...p, cursor: p.cursor }))}
                  >
                    Next
                  </button>
                </div>
              </div>
            </>
          )}

          {/* Claim Detail Drawer */}
          {selectedClaim && (
            <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50">
              <div className="bg-white rounded-lg shadow-xl max-w-3xl w-full max-h-[90vh] overflow-hidden flex flex-col">
                <div className="p-4 border-b flex justify-between items-center">
                  <div>
                    <h2 className="text-xl font-semibold">Claim Details</h2>
                    <p className="text-sm text-gray-500">{selectedClaim.claim_id}</p>
                  </div>
                  <button onClick={() => setSelectedClaim(null)} className="text-gray-500 hover:text-gray-700 text-2xl">✕</button>
                </div>
                <div className="p-4 overflow-y-auto flex-1 space-y-4">
                  <div className="grid grid-cols-2 gap-4">
                    <div><p className="text-sm text-gray-500">State</p><p className={`font-medium px-2 py-1 rounded inline-block ${stateColor(selectedClaim.claim_state)}`}>{selectedClaim.claim_state.replace('_', ' ')}</p></div>
                    <div><p className="text-sm text-gray-500">Confidence</p><p className="font-medium">{formatConfidence(selectedClaim.confidence)}</p></div>
                    <div><p className="text-sm text-gray-500">Entity</p><p className="font-medium">{selectedClaim.canonical_entity || '—'}</p></div>
                    <div><p className="text-sm text-gray-500">Field</p><p className="font-medium">{selectedClaim.canonical_field || '—'}</p></div>
                    <div><p className="text-sm text-gray-500">Source Column</p><p className="font-medium">{selectedClaim.source_column}</p></div>
                    <div><p className="text-sm text-gray-500">Requires Review</p><p className="font-medium">{selectedClaim.requires_review ? 'Yes' : 'No'}</p></div>
                  </div>
                  <div>
                    <p className="text-sm text-gray-500 mb-1">Raw Value</p>
                    <p className="font-mono bg-gray-50 p-3 rounded">{selectedClaim.raw_value}</p>
                  </div>
                  <div>
                    <p className="text-sm text-gray-500 mb-1">Normalized Value</p>
                    <p className="font-mono bg-gray-50 p-3 rounded">{selectedClaim.normalized_value || '—'}</p>
                  </div>
                  <div>
                    <p className="text-sm text-gray-500 mb-1">Provenance</p>
                    <pre className="bg-gray-50 p-3 rounded text-xs overflow-auto">{JSON.stringify(selectedClaim, null, 2)}</pre>
                  </div>
                </div>
                <div className="p-4 border-t flex justify-end gap-2">
                  <button onClick={() => setSelectedClaim(null)} className="px-4 py-2 border rounded text-gray-700 hover:bg-gray-50">Close</button>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default function EvidencePage() {
  return (
    <Suspense fallback={<div className="p-8 font-mono text-sm text-[#666666]">Loading evidence records...</div>}>
      <EvidenceContent />
    </Suspense>
  )
}