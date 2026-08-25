'use client'

import { useState, useEffect, useCallback, useMemo, Suspense } from 'react'
import { useSearchParams } from 'next/navigation'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000/api/v1'

// Types
interface AuditEvent {
  event_id: string
  event_type: string
  event_category: string
  workspace_id: string | null
  subject_type: string | null
  subject_id: string | null
  message: string | null
  occurred_at: string
  payload: Record<string, any>
  correlation_id: string | null
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

function formatDate(iso: string) { return new Date(iso).toLocaleString() }
function truncate(str: string, len: number) { return str.length > len ? str.slice(0, len) + '…' : str }

function AuditContent() {
  const searchParams = useSearchParams()
  const workspaceId = searchParams.get('workspace_id') || 'default-workspace'
  
  const [events, setEvents] = useState<AuditEvent[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [total, setTotal] = useState(0)
  
  // Filters
  const [filters, setFilters] = useState({
    event_type: '' as string,
    category: 'all' as string,
    subject_id: '' as string,
    from: '' as string,
    to: '' as string,
    search: '' as string,
  })
  const [pagination, setPagination] = useState({ page: 1, pageSize: 50 })
  const [sort, setSort] = useState<{ field: string; dir: 'asc' | 'desc' }>({ field: 'occurred_at', dir: 'desc' })
  const [selectedEvent, setSelectedEvent] = useState<AuditEvent | null>(null)

  // Category colors
  const categoryColors: Record<string, string> = {
    audit: 'bg-purple-100 text-purple-800',
    business: 'bg-green-100 text-green-800',
    system: 'bg-blue-100 text-blue-800',
    domain: 'bg-orange-100 text-orange-800',
    integration: 'bg-pink-100 text-pink-800',
  }

  const fetchEvents = useCallback(async () => {
    try {
      setLoading(true)
      const params = new URLSearchParams()
      params.set('workspace_id', workspaceId)
      params.set('limit', String(pagination.pageSize))
      params.set('offset', String((pagination.page - 1) * pagination.pageSize))
      if (filters.event_type) params.set('event_type', filters.event_type)
      if (filters.category !== 'all') params.set('category', filters.category)
      if (filters.subject_id) params.set('subject_id', filters.subject_id)
      if (filters.from) params.set('from', filters.from)
      if (filters.to) params.set('to', filters.to)
      if (filters.search) params.set('search', filters.search)
      
      const data = await api<AuditEvent[]>(`/audit?${params.toString()}`)
      setEvents(data)
      // In a real implementation, total would come from a separate count endpoint
      setTotal(data.length)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [workspaceId, pagination, filters])

  useEffect(() => { fetchEvents() }, [fetchEvents])

  const filteredEvents = useMemo(() => {
    return events
      .filter(e => !filters.search || 
        e.event_type.toLowerCase().includes(filters.search.toLowerCase()) ||
        e.message?.toLowerCase().includes(filters.search.toLowerCase()) ||
        JSON.stringify(e.payload).toLowerCase().includes(filters.search.toLowerCase()))
      .sort((a, b) => {
        const aVal = a[sort.field as keyof AuditEvent] as string | number | null
        const bVal = b[sort.field as keyof AuditEvent] as string | number | null
        const aCmp = aVal ?? ''
        const bCmp = bVal ?? ''
        if (aCmp < bCmp) return sort.dir === 'asc' ? -1 : 1
        if (aCmp > bCmp) return sort.dir === 'asc' ? 1 : -1
        return 0
      })
  }, [events, filters.search, sort])

  const handleSort = (field: string) => {
    setSort(prev => ({
      field,
      dir: prev.field === field && prev.dir === 'asc' ? 'desc' : 'asc'
    }))
  }

  const sortableHeaders = [
    { key: 'event_type', label: 'Type' },
    { key: 'event_category', label: 'Category' },
    { key: 'subject_type', label: 'Subject Type' },
    { key: 'subject_id', label: 'Subject ID' },
    { key: 'occurred_at', label: 'Time' },
  ]

  const formatPayload = (payload: Record<string, any>) => {
    return JSON.stringify(payload, null, 2)
  }

  return (
    <div className="min-h-screen p-6 bg-gray-50">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="mb-8 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <h1 className="text-3xl font-bold text-gray-900">Audit Trail</h1>
            <p className="text-gray-600 mt-1">Immutable record of all platform actions</p>
          </div>
          <div className="flex gap-3">
            <button className="px-4 py-2 border rounded text-sm text-gray-700 hover:bg-gray-50">
              Export CSV
            </button>
            <button className="px-4 py-2 border rounded text-sm text-gray-700 hover:bg-gray-50">
              Export JSON
            </button>
          </div>
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
                placeholder="Search event type, message, payload…"
                className="w-full border rounded px-3 py-2"
              />
            </div>
            <div className="min-w-[150px]">
              <label className="block text-sm font-medium text-gray-700 mb-1">Category</label>
              <select
                value={filters.category}
                onChange={e => setFilters(prev => ({ ...prev, category: e.target.value, page: 1 }))}
                className="w-full border rounded px-3 py-2"
              >
                <option value="all">All Categories</option>
                <option value="audit">Audit</option>
                <option value="business">Business</option>
                <option value="system">System</option>
                <option value="domain">Domain</option>
                <option value="integration">Integration</option>
              </select>
            </div>
            <div className="min-w-[180px]">
              <label className="block text-sm font-medium text-gray-700 mb-1">Event Type</label>
              <input
                type="text"
                value={filters.event_type}
                onChange={e => setFilters(prev => ({ ...prev, event_type: e.target.value, page: 1 }))}
                placeholder="Filter by type"
                className="w-full border rounded px-3 py-2"
              />
            </div>
            <div className="min-w-[180px]">
              <label className="block text-sm font-medium text-gray-700 mb-1">Subject ID</label>
              <input
                type="text"
                value={filters.subject_id}
                onChange={e => setFilters(prev => ({ ...prev, subject_id: e.target.value, page: 1 }))}
                placeholder="Filter by subject"
                className="w-full border rounded px-3 py-2"
              />
            </div>
            <div className="flex items-end gap-2">
              <div className="flex items-center gap-2">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={filters.category !== 'all' && filters.category === 'audit'}
                    onChange={e => setFilters(prev => ({ ...prev, category: e.target.checked ? 'audit' : 'all', page: 1 }))}
                    className="rounded border-gray-300"
                  />
                  <span className="text-sm">Audit only</span>
                </label>
              </div>
            </div>
          </div>

          {/* Date Range */}
          <div className="mt-4 flex flex-wrap gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">From</label>
              <input
                type="datetime-local"
                value={filters.from}
                onChange={e => setFilters(prev => ({ ...prev, from: e.target.value, page: 1 }))}
                className="w-full border rounded px-3 py-2"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">To</label>
              <input
                type="datetime-local"
                value={filters.to}
                onChange={e => setFilters(prev => ({ ...prev, to: e.target.value, page: 1 }))}
                className="w-full border rounded px-3 py-2"
              />
            </div>
            <div className="flex items-end">
              <button
                onClick={() => setFilters(prev => ({ ...prev, from: '', to: '', page: 1 }))}
                className="text-sm text-blue-600 hover:underline"
              >
                Clear dates
              </button>
            </div>
          </div>
        </div>

        {/* Event Table */}
        <div className="bg-white rounded-lg shadow-sm border">
          {loading ? (
            <div className="p-8 text-center text-gray-500">Loading events…</div>
          ) : error ? (
            <div className="p-4 text-red-600">{error}</div>
          ) : events.length === 0 ? (
            <div className="p-8 text-center text-gray-500">No events found. Try adjusting filters.</div>
          ) : (
            <>
              {/* Header */}
              <div className="p-4 border-b bg-gray-50 flex flex-wrap gap-4 items-center">
                <span className="text-sm text-gray-600">
                  Showing {events.length} events
                </span>
                <div className="flex gap-2">
                  <select
                    value={pagination.pageSize}
                    onChange={e => setPagination(prev => ({ ...prev, pageSize: parseInt(e.target.value), page: 1 }))}
                    className="border rounded px-2 py-1 text-sm"
                  >
                    <option value={25}>25 per page</option>
                    <option value={50}>50 per page</option>
                    <option value={100}>100 per page</option>
                    <option value={200}>200 per page</option>
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
                              <span>{sort.dir === 'asc' ? '↑' : '↓'}</span>
                            )}
                          </div>
                        </th>
                      ))}
                      <th className="px-4 py-3">Message</th>
                      <th className="px-4 py-3">Payload</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-200">
                    {events.map(event => (
                      <tr key={event.event_id} className="hover:bg-gray-50">
                        <td className="px-4 py-3">
                          <span className="text-sm font-mono text-gray-500">{event.event_id.slice(0, 12)}…</span>
                        </td>
                        <td className="px-4 py-3">
                          <span className={`px-2 py-1 text-xs rounded ${categoryColors[event.event_category] || 'bg-gray-100 text-gray-800'}`}>
                            {event.event_category}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-sm text-gray-600">{event.subject_type || '—'}</td>
                        <td className="px-4 py-3 text-sm font-mono text-gray-500">
                          {event.subject_id ? event.subject_id.slice(0, 12) + '…' : '—'}
                        </td>
                        <td className="px-4 py-3 text-sm text-gray-500">{formatDate(event.occurred_at)}</td>
                        <td className="px-4 py-3 text-sm text-gray-600 max-w-xs truncate">{event.event_type}</td>
                        <td className="px-4 py-3 text-sm text-gray-600 max-w-xs truncate">{event.message || '—'}</td>
                        <td className="px-4 py-3">
                          <button
                            onClick={() => setSelectedEvent(event)}
                            className="text-sm text-blue-600 hover:text-blue-800"
                          >
                            Details
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Pagination */}
              <div className="p-4 border-t flex justify-between items-center text-sm text-gray-500">
                <span>
                  Page {pagination.page}
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
                    disabled={events.length < pagination.pageSize}
                    onClick={() => setPagination(p => ({ ...p, page: p.page + 1 }))}
                  >
                    Next
                  </button>
                </div>
              </div>
            </>
          )}
        </div>

        {/* Event Detail Modal */}
        {selectedEvent && (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50">
            <div className="bg-white rounded-lg shadow-xl max-w-4xl w-full max-h-[90vh] overflow-hidden flex flex-col">
              <div className="p-4 border-b flex justify-between items-center">
                <div>
                  <h2 className="text-xl font-semibold">Event Details</h2>
                  <p className="text-sm text-gray-500">
                    {selectedEvent.event_category} • {selectedEvent.event_type} • {formatDate(selectedEvent.occurred_at)}
                  </p>
                </div>
                <button onClick={() => setSelectedEvent(null)} className="text-gray-500 hover:text-gray-700 text-2xl">✕</button>
              </div>
              <div className="p-4 overflow-y-auto flex-1 space-y-6">
                {/* Summary */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4 p-4 bg-gray-50 rounded">
                  <div>
                    <p className="text-sm text-gray-500">Event ID</p>
                    <p className="font-mono text-sm text-gray-900">{selectedEvent.event_id}</p>
                  </div>
                  <div>
                    <p className="text-sm text-gray-500">Category</p>
                    <p className="text-sm font-medium">
                      <span className={`px-2 py-0.5 text-xs rounded ${categoryColors[selectedEvent.event_category] || 'bg-gray-100 text-gray-800'}`}>
                        {selectedEvent.event_category}
                      </span>
                    </p>
                  </div>
                  <div>
                    <p className="text-sm text-gray-500">Type</p>
                    <p className="text-sm font-mono text-gray-900">{selectedEvent.event_type}</p>
                  </div>
                  <div>
                    <p className="text-sm text-gray-500">Time</p>
                    <p className="text-sm text-gray-900">{formatDate(selectedEvent.occurred_at)}</p>
                  </div>
                  <div className="md:col-span-2">
                    <p className="text-sm text-gray-500">Workspace</p>
                    <p className="text-sm font-mono text-gray-900">{selectedEvent.workspace_id || '—'}</p>
                  </div>
                  <div className="md:col-span-2">
                    <p className="text-sm text-gray-500">Subject</p>
                    <p className="text-sm font-mono text-gray-900">
                      {selectedEvent.subject_type || '—'} : {selectedEvent.subject_id || '—'}
                    </p>
                  </div>
                  <div className="md:col-span-2">
                    <p className="text-sm text-gray-500">Correlation ID</p>
                    <p className="text-sm font-mono text-gray-900">{selectedEvent.correlation_id || '—'}</p>
                  </div>
                </div>

                {/* Message */}
                {selectedEvent.message && (
                  <div>
                    <h3 className="text-lg font-semibold mb-2">Message</h3>
                    <p className="p-4 bg-gray-50 rounded text-gray-900">{selectedEvent.message}</p>
                  </div>
                )}

                {/* Payload */}
                <div>
                  <div className="flex items-center justify-between mb-2">
                    <h3 className="text-lg font-semibold">Payload</h3>
                    <button
                      onClick={() => navigator.clipboard.writeText(formatPayload(selectedEvent.payload))}
                      className="text-sm text-blue-600 hover:text-blue-800"
                    >
                      Copy JSON
                    </button>
                  </div>
                  <pre className="bg-gray-900 text-gray-100 p-4 rounded overflow-x-auto text-sm max-h-96 overflow-y-auto">
                    <code>{formatPayload(selectedEvent.payload)}</code>
                  </pre>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

export default function AuditPage() {
  return (
    <Suspense fallback={<div className="p-8 font-mono text-sm text-[#666666]">Loading audit telemetry...</div>}>
      <AuditContent />
    </Suspense>
  )
}