'use client'

import { useState, useEffect, useCallback, useMemo, Suspense } from 'react'
import { useSearchParams } from 'next/navigation'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000/api/v1'

// Types
interface EvidenceConflict {
  conflict_id: string
  claim_ids: string[]
  canonical_entity: string | null
  canonical_field: string | null
  severity: string
  blocking: boolean
  status: string
  explanation: string
  created_at: string
}

interface ResolveRequest {
  selected_claim_id: string | null
  action: string
  rationale: string
}

interface Claim {
  claim_id: string
  source_column: string
  canonical_entity: string | null
  canonical_field: string | null
  raw_value: string
  normalized_value: string | null
  confidence: number
  claim_state: string
}

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

function formatDate(iso: string) {
  return new Date(iso).toLocaleString()
}

function severityColor(severity: string) {
  switch (severity) {
    case 'critical': return 'bg-red-100 text-red-800'
    case 'major': return 'bg-orange-100 text-orange-800'
    case 'warning': return 'bg-yellow-100 text-yellow-800'
    case 'info': return 'bg-blue-100 text-blue-800'
    default: return 'bg-gray-100 text-gray-800'
  }
}

function statusColor(status: string) {
  switch (status) {
    case 'open': return 'bg-red-100 text-red-800'
    case 'resolved': return 'bg-green-100 text-green-800'
    case 'escalated': return 'bg-orange-100 text-orange-800'
    default: return 'bg-gray-100 text-gray-800'
  }
}

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

// Conflict Center Page
function ConflictsContent() {
  const searchParams = useSearchParams()
  const workspaceId = searchParams.get('workspace_id') || 'default-workspace'
  const batchId = searchParams.get('batch_id')
  
  const [conflicts, setConflicts] = useState<EvidenceConflict[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedConflict, setSelectedConflict] = useState<EvidenceConflict | null>(null)
  const [claims, setClaims] = useState<Record<string, Claim[]>>({})
  const [resolving, setResolving] = useState<string | null>(null)

  const [filters, setFilters] = useState({
    severity: 'all' as string,
    status: 'all' as string,
    blockingOnly: false,
    search: '',
  })
  const [pagination, setPagination] = useState({ page: 1, pageSize: 25 })
  const [sort, setSort] = useState<{ field: string; direction: 'asc' | 'desc' }>({ field: 'created_at', direction: 'desc' })

  const fetchConflicts = useCallback(async () => {
    try {
      setLoading(true)
      let url = `/conflicts?workspace_id=${workspaceId}`
      if (batchId) url += `&batch_id=${batchId}`
      const data = await api<EvidenceConflict[]>(url)
      setConflicts(data)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [workspaceId, batchId])

  useEffect(() => { fetchConflicts() }, [fetchConflicts])

  // Load claims for selected conflict
  useEffect(() => {
    if (!selectedConflict) return
    const fetch = async () => {
      try {
        const data = await api<Claim[]>(`/conflicts/${selectedConflict.conflict_id}/claims`)
        setClaims(prev => ({ ...prev, [selectedConflict.conflict_id]: data }))
      } catch (e) { console.error(e) }
    }
    fetch()
  }, [selectedConflict])

  const filteredConflicts = useMemo(() => {
    return conflicts
      .filter(c => filters.severity === 'all' || c.severity === filters.severity)
      .filter(c => filters.status === 'all' || c.status === filters.status)
      .filter(c => !filters.blockingOnly || c.blocking)
      .filter(c => !filters.search || 
        c.explanation.toLowerCase().includes(filters.search.toLowerCase()) ||
        c.conflict_id.toLowerCase().includes(filters.search.toLowerCase()) ||
        c.canonical_field?.toLowerCase().includes(filters.search.toLowerCase()) ||
        c.canonical_entity?.toLowerCase().includes(filters.search.toLowerCase()))
      .sort((a, b) => {
        const aVal = a[sort.field as keyof EvidenceConflict] as string | number | null
        const bVal = b[sort.field as keyof EvidenceConflict] as string | number | null
        const aCmp = aVal ?? ''
        const bCmp = bVal ?? ''
        if (aCmp < bCmp) return sort.direction === 'asc' ? -1 : 1
        if (aCmp > bCmp) return sort.direction === 'asc' ? 1 : -1
        return 0
      })
  }, [conflicts, filters, sort])

  const paginatedConflicts = useMemo(() => {
    const start = (pagination.page - 1) * pagination.pageSize
    return filteredConflicts.slice(start, start + pagination.pageSize)
  }, [filteredConflicts, pagination])

  const handleResolve = async (conflictId: string, selectedClaimId: string | null, action: string, rationale: string) => {
    setResolving(conflictId)
    try {
      await api(`/conflicts/${conflictId}/resolve?workspace_id=${workspaceId}`, {
        method: 'POST',
        body: JSON.stringify({ selected_claim_id: selectedClaimId, action, rationale }),
      })
      setSelectedConflict(null)
      fetchConflicts()
    } catch (e: any) {
      alert(`Failed to resolve: ${e.message}`)
    } finally {
      setResolving(null)
    }
  }

  const handleSort = (field: string) => {
    setSort(prev => ({
      field,
      direction: prev.field === field && prev.direction === 'asc' ? 'desc' : 'asc'
    }))
  }

  const sortableHeaders = [
    { key: 'severity', label: 'Severity' },
    { key: 'status', label: 'Status' },
    { key: 'blocking', label: 'Blocking' },
    { key: 'canonical_entity', label: 'Entity' },
    { key: 'canonical_field', label: 'Field' },
    { key: 'created_at', label: 'Detected' },
  ]

  return (
    <div className="min-h-screen p-6 bg-gray-50">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="mb-8">
          <h1 className="text-3xl font-bold text-gray-900">Conflict Center</h1>
          <p className="text-gray-600 mt-1">Review and resolve conflicting evidence claims</p>
        </div>

        {/* Filters */}
        <div className="bg-white rounded-lg shadow-sm border mb-6 p-4">
          <div className="flex flex-wrap gap-4 items-end">
            <div className="flex-1 min-w-[200px]">
              <label className="block text-sm font-medium text-gray-700 mb-1">Search</label>
              <input
                type="text"
                value={filters.search}
                onChange={e => setFilters(prev => ({ ...prev, search: e.target.value, page: 1 }))}
                placeholder="Search conflicts, entities, fields..."
                className="w-full border rounded px-3 py-2"
              />
            </div>
            <div className="min-w-[150px]">
              <label className="block text-sm font-medium text-gray-700 mb-1">Severity</label>
              <select
                value={filters.severity}
                onChange={e => setFilters(prev => ({ ...prev, severity: e.target.value, page: 1 }))}
                className="w-full border rounded px-3 py-2"
              >
                <option value="all">All Severities</option>
                <option value="critical">Critical</option>
                <option value="major">Major</option>
                <option value="warning">Warning</option>
                <option value="info">Info</option>
              </select>
            </div>
            <div className="min-w-[150px]">
              <label className="block text-sm font-medium text-gray-700 mb-1">Status</label>
              <select
                value={filters.status}
                onChange={e => setFilters(prev => ({ ...prev, status: e.target.value, page: 1 }))}
                className="w-full border rounded px-3 py-2"
              >
                <option value="all">All Statuses</option>
                <option value="open">Open</option>
                <option value="resolved">Resolved</option>
                <option value="escalated">Escalated</option>
              </select>
            </div>
            <div className="flex items-end">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={filters.blockingOnly}
                  onChange={e => setFilters(prev => ({ ...prev, blockingOnly: e.target.checked, page: 1 }))}
                  className="rounded border-gray-300"
                />
                <span className="text-sm">Blocking only</span>
              </label>
            </div>
          </div>
        </div>

        {/* Conflict List */}
        <div className="bg-white rounded-lg shadow-sm border">
          {loading ? (
            <div className="p-8 text-center text-gray-500">Loading conflicts…</div>
          ) : error ? (
            <div className="p-4 text-red-600">{error}</div>
          ) : filteredConflicts.length === 0 ? (
            <div className="p-8 text-center text-gray-500">
              No conflicts found. {filters.search && <button onClick={() => setFilters(prev => ({ ...prev, search: '' }))} className="text-blue-600 hover:underline">Clear search</button>}
            </div>
          ) : (
            <>
              {/* Header */}
              <div className="p-4 border-b bg-gray-50 flex flex-wrap gap-4 items-center">
                <span className="text-sm text-gray-600">
                  Showing {paginatedConflicts.length} of {filteredConflicts.length} conflicts
                </span>
                <div className="flex gap-2">
                  <select
                    value={pagination.pageSize}
                    onChange={e => setPagination(prev => ({ ...prev, pageSize: parseInt(e.target.value), page: 1 }))}
                    className="border rounded px-2 py-1 text-sm"
                  >
                    <option value={10}>10 per page</option>
                    <option value={25}>25 per page</option>
                    <option value={50}>50 per page</option>
                    <option value={100}>100 per page</option>
                  </select>
                </div>
              </div>

              {/* Table */}
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead className="bg-gray-50">
                    <tr className="text-left text-sm text-gray-500">
                      {sortableHeaders.map(h => (
                        <th key={h.key} className="px-4 py-3 cursor-pointer hover:bg-gray-100"
                            onClick={() => handleSort(h.key)}>
                          <div className="flex items-center gap-1">
                            {h.label}
                            {sort.field === h.key && (
                              <span>{sort.direction === 'asc' ? '↑' : '↓'}</span>
                            )}
                          </div>
                        </th>
                      ))}
                      <th className="px-4 py-3">Explanation</th>
                      <th className="px-4 py-3">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-200">
                    {paginatedConflicts.map(conflict => (
                      <tr key={conflict.conflict_id} className="hover:bg-gray-50">
                        <td className="px-4 py-3">
                          <span className={`px-2 py-1 text-xs rounded ${severityColor(conflict.severity)}`}>
                            {conflict.severity}
                          </span>
                        </td>
                        <td className="px-4 py-3">
                          <span className={`px-2 py-1 text-xs rounded ${statusColor(conflict.status)}`}>
                            {conflict.status}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-center">
                          {conflict.blocking ? (
                            <span className="px-2 py-1 text-xs bg-red-100 text-red-800 rounded">Blocking</span>
                          ) : (
                            <span className="text-gray-400">—</span>
                          )}
                        </td>
                        <td className="px-4 py-3 text-sm text-gray-900">{conflict.canonical_entity || '—'}</td>
                        <td className="px-4 py-3 text-sm text-gray-600">{conflict.canonical_field || '—'}</td>
                        <td className="px-4 py-3 text-sm text-gray-500">{formatDate(conflict.created_at)}</td>
                        <td className="px-4 py-3 text-sm text-gray-600 max-w-xs truncate">{conflict.explanation}</td>
                        <td className="px-4 py-3">
                          <button
                            onClick={() => setSelectedConflict(conflict)}
                            className="text-sm text-blue-600 hover:text-blue-800"
                          >
                            Review
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>

                {/* Pagination */}
                <div className="p-4 border-t flex justify-between items-center text-sm text-gray-500">
                  <span>
                    Page {pagination.page} of {Math.ceil(filteredConflicts.length / pagination.pageSize) || 1}
                  </span>
                  <div className="flex gap-2">
                    <button
                      className="px-3 py-1 border rounded disabled:opacity-50"
                      disabled={pagination.page === 1}
                      onClick={() => setPagination(p => ({ ...p, page: p.page - 1 }))}
                    >
                      Previous
                    </button>
                    <button
                      className="px-3 py-1 border rounded disabled:opacity-50"
                      disabled={pagination.page * pagination.pageSize >= filteredConflicts.length}
                      onClick={() => setPagination(p => ({ ...p, page: p.page + 1 }))}
                    >
                      Next
                    </button>
                  </div>
                </div>
              </div>
            </>
          )}
        </div>

        {/* Conflict Detail Modal */}
        {selectedConflict && (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50">
            <div className="bg-white rounded-lg shadow-xl max-w-4xl w-full max-h-[90vh] overflow-hidden flex flex-col">
              {/* Header */}
              <div className="p-4 border-b flex justify-between items-center">
                <div>
                  <h2 className="text-xl font-semibold">Conflict Review</h2>
                  <p className="text-sm text-gray-500">
                    {selectedConflict.claim_ids.length} conflicting claims •{' '}
                    <span className={`px-2 py-0.5 text-xs rounded ${severityColor(selectedConflict.severity)}`}>
                      {selectedConflict.severity}
                    </span>
                    {' '}
                    <span className={`px-2 py-0.5 text-xs rounded ${statusColor(selectedConflict.status)}`}>
                      {selectedConflict.status}
                    </span>
                    {selectedConflict.blocking && <span className="ml-2 px-2 py-0.5 text-xs bg-red-100 text-red-800 rounded">Blocking</span>}
                  </p>
                </div>
                <button onClick={() => setSelectedConflict(null)} className="text-gray-500 hover:text-gray-700 text-2xl">✕</button>
              </div>

              {/* Claims Comparison */}
              <div className="p-4 border-b overflow-x-auto">
                <h3 className="text-lg font-semibold mb-3">Conflicting Claims</h3>
                {claims[selectedConflict.conflict_id] && claims[selectedConflict.conflict_id].length > 0 ? (
                  <div className="overflow-x-auto">
                    <table className="w-full">
                      <thead className="bg-gray-50">
                        <tr className="text-left text-sm text-gray-500">
                          <th className="px-4 py-2">Claim ID</th>
                          <th className="px-4 py-2">Source Column</th>
                          <th className="px-4 py-2">Entity</th>
                          <th className="px-4 py-2">Field</th>
                          <th className="px-4 py-2">Raw Value</th>
                          <th className="px-4 py-2">Normalized</th>
                          <th className="px-4 py-2">Confidence</th>
                          <th className="px-4 py-2">State</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-gray-200">
                        {claims[selectedConflict.conflict_id].map(claim => (
                          <tr key={claim.claim_id} className="hover:bg-gray-50">
                            <td className="px-4 py-2 text-sm font-mono text-gray-500">{claim.claim_id.slice(0, 12)}…</td>
                            <td className="px-4 py-2 text-sm text-gray-600">{claim.source_column}</td>
                            <td className="px-4 py-2 text-sm text-gray-900">{claim.canonical_entity || '—'}</td>
                            <td className="px-4 py-2 text-sm text-gray-600">{claim.canonical_field || '—'}</td>
                            <td className="px-4 py-2 text-sm font-mono text-gray-600 max-w-xs truncate">{claim.raw_value}</td>
                            <td className="px-4 py-2 text-sm text-gray-600 max-w-xs truncate">{claim.normalized_value || '—'}</td>
                            <td className="px-4 py-2 text-sm">
                              <div className="flex items-center gap-2">
                                <div className="w-20 h-2 bg-gray-200 rounded overflow-hidden">
                                  <div className="h-full bg-green-500" style={{ width: `${claim.confidence * 100}%` }} />
                                </div>
                                <span className="text-xs">{(claim.confidence * 100).toFixed(0)}%</span>
                              </div>
                            </td>
                            <td className="px-4 py-2">
                              <span className={`px-2 py-1 text-xs rounded ${stateColor(claim.claim_state)}`}>
                                {claim.claim_state}
                              </span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <p className="text-gray-500 py-4">Loading claims…</p>
                )}
              </div>

              {/* Resolution Form */}
              <div className="p-4 border-b">
                <h3 className="text-lg font-semibold mb-3">Resolve Conflict</h3>
                <form onSubmit={e => {
                  e.preventDefault()
                  const formData = new FormData(e.currentTarget)
                  const selected = formData.get('selected_claim')
                  handleResolve(
                    selectedConflict.conflict_id,
                    selected === 'none' ? null : (selected as string | null),
                    formData.get('action') as string,
                    formData.get('rationale') as string
                  )
                }}>
                  <div className="space-y-4">
                    <div>
                      <label className="block text-sm font-medium mb-2">Select Claim to Accept</label>
                      <div className="space-y-2">
                        {claims[selectedConflict.conflict_id]?.map(claim => (
                          <label key={claim.claim_id} className="flex items-center gap-3 p-3 border rounded hover:bg-gray-50 cursor-pointer">
                            <input
                              type="radio"
                              name="selected_claim"
                              value={claim.claim_id}
                              className="text-blue-600"
                            />
                            <div>
                              <p className="font-mono text-sm text-gray-600">{claim.raw_value}</p>
                              <p className="text-xs text-gray-500">
                                {claim.source_column} → {claim.canonical_field} ({claim.canonical_entity})
                              </p>
                              <p className="text-xs text-gray-500">Confidence: {(claim.confidence * 100).toFixed(0)}%</p>
                            </div>
                          </label>
                        ))}
                        <label className="flex items-center gap-3 p-3 border rounded hover:bg-gray-50 cursor-pointer">
                          <input type="radio" name="selected_claim" value="none" className="text-blue-600" />
                          <span className="text-gray-600">Reject all / Suppress conflict</span>
                        </label>
                      </div>
                    </div>

                    <div>
                      <label className="block text-sm font-medium mb-2">Action</label>
                      <select name="action" className="w-full border rounded px-3 py-2" required>
                        <option value="approved">Approve Selected</option>
                        <option value="rejected">Reject Selected</option>
                        <option value="suppressed">Suppress Conflict</option>
                        <option value="escalated">Escalate</option>
                      </select>
                    </div>

                    <div>
                      <label className="block text-sm font-medium mb-2">Rationale (required)</label>
                      <textarea
                        name="rationale"
                        rows={3}
                        required
                        className="w-full border rounded px-3 py-2"
                        placeholder="Explain why this resolution was chosen…"
                      />
                    </div>

                    <div className="flex justify-end gap-3 pt-4">
                      <button
                        type="button"
                        onClick={() => setSelectedConflict(null)}
                        className="px-4 py-2 border rounded text-gray-700 hover:bg-gray-50"
                      >
                        Cancel
                      </button>
                      <button
                        type="submit"
                        disabled={resolving === selectedConflict.conflict_id}
                        className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
                      >
                        {resolving === selectedConflict.conflict_id ? 'Resolving…' : 'Resolve Conflict'}
                      </button>
                    </div>
                  </div>
                </form>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

export default function ConflictsPage() {
  return (
    <Suspense fallback={<div className="p-8 font-mono text-sm text-[#666666]">Loading conflict center...</div>}>
      <ConflictsContent />
    </Suspense>
  )
}