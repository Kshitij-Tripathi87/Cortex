'use client'

import { useState, useEffect, useCallback, Suspense } from 'react'
import { useSearchParams } from 'next/navigation'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000/api/v1'

interface ReadinessAssessment {
  assessment_id: string
  batch_id: string
  workspace_id: string
  state: string
  blocking_conflict_count: number
  open_conflict_count: number
  accepted_claim_count: number
  pending_claim_count: number
  assumptions: string[]
  explanation: string
  created_at: string
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

function formatDate(iso: string) { return new Date(iso).toLocaleString() }
function stateColor(state: string) {
  switch (state) {
    case 'ready': return 'bg-green-100 text-green-800'
    case 'ready_with_assumptions': return 'bg-amber-100 text-amber-800'
    case 'review_required': return 'bg-yellow-100 text-yellow-800'
    case 'blocked': return 'bg-red-100 text-red-800'
    default: return 'bg-gray-100 text-gray-800'
  }
}

function ReadinessContent() {
  const searchParams = useSearchParams()
  const workspaceId = searchParams.get('workspace_id') || 'default-workspace'
  
  const [assessments, setAssessments] = useState<ReadinessAssessment[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<ReadinessAssessment | null>(null)

  const fetchAssessments = useCallback(async () => {
    try {
      setLoading(true)
      const data = await api<ReadinessAssessment[]>(`/readiness?workspace_id=${workspaceId}`)
      setAssessments(data)
    } catch (e: any) { setError(e.message) }
    finally { setLoading(false) }
  }, [workspaceId])

  useEffect(() => { fetchAssessments() }, [fetchAssessments])

  const computeReadiness = async (batchId: string) => {
    try {
      const result = await api<ReadinessAssessment>(`/readiness/batches/${batchId}`, { method: 'POST' })
      setSelected(result)
      fetchAssessments()
    } catch (e: any) { alert(`Failed: ${e.message}`) }
  }

  const stateLabel = (state: string) => {
    switch (state) {
      case 'ready': return 'Ready'
      case 'blocked': return 'Blocked'
      case 'review_required': return 'Review Required'
      case 'ready_with_assumptions': return 'Ready (with Assumptions)'
      default: return state
    }
  }

  return (
    <div className="min-h-screen p-6 bg-gray-50">
      <div className="max-w-7xl mx-auto">
        <div className="mb-8">
          <h1 className="text-3xl font-bold text-gray-900">Readiness Center</h1>
          <p className="text-gray-600 mt-1">Determine if your data is ready for downstream operational intelligence</p>
        </div>

        {/* Compute Button */}
        <div className="mb-6">
          <button
            onClick={() => {
              const batchId = prompt('Enter Batch ID to compute readiness:')
              if (batchId) computeReadiness(batchId)
            }}
            className="px-4 py-2 bg-green-600 text-white rounded hover:bg-green-700"
          >
            Compute Readiness for Batch
          </button>
        </div>

        {/* Assessments List */}
        <div className="bg-white rounded-lg shadow-sm border">
          {loading ? (
            <div className="p-8 text-center text-gray-500">Loading assessments…</div>
          ) : error ? (
            <div className="p-4 text-red-600">{error}</div>
          ) : assessments.length === 0 ? (
            <div className="p-8 text-center text-gray-500">
              No readiness assessments yet. Compute readiness for a batch to get started.
            </div>
          ) : (
            <>
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead className="bg-gray-50">
                    <tr className="text-left text-sm text-gray-500">
                      <th className="px-4 py-3">Batch ID</th>
                      <th className="px-4 py-3">State</th>
                      <th className="px-4 py-3">Blocking Conflicts</th>
                      <th className="px-4 py-3">Open Conflicts</th>
                      <th className="px-4 py-3">Accepted Claims</th>
                      <th className="px-4 py-3">Pending Claims</th>
                      <th className="px-4 py-3">Created</th>
                      <th className="px-4 py-3">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-200">
                    {assessments.map(a => (
                      <tr key={a.assessment_id} className="hover:bg-gray-50">
                        <td className="px-4 py-3 font-mono text-sm text-gray-500">{a.batch_id.slice(0, 12)}…</td>
                        <td className="px-4 py-3">
                          <span className={`px-2 py-1 text-xs rounded ${stateColor(a.state)}`}>
                            {stateLabel(a.state)}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-center">
                          {a.blocking_conflict_count > 0 ? (
                            <span className="px-2 py-1 text-xs bg-red-100 text-red-800 rounded">
                              {a.blocking_conflict_count}
                            </span>
                          ) : '0'}
                        </td>
                        <td className="px-4 py-3 text-center">{a.open_conflict_count}</td>
                        <td className="px-4 py-3 text-center">{a.accepted_claim_count}</td>
                        <td className="px-4 py-3 text-center">{a.pending_claim_count}</td>
                        <td className="px-4 py-3 text-sm text-gray-500">{formatDate(a.created_at)}</td>
                        <td className="px-4 py-3">
                          <button
                            onClick={() => setSelected(a)}
                            className="text-sm text-blue-600 hover:text-blue-800"
                          >
                            View Details
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>

        {/* Detail Modal */}
        {selected && (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50">
            <div className="bg-white rounded-lg shadow-xl max-w-4xl w-full max-h-[90vh] overflow-hidden flex flex-col">
              <div className="p-4 border-b flex justify-between items-center">
                <div>
                  <h2 className="text-xl font-semibold">Readiness Assessment</h2>
                  <p className="text-sm text-gray-500">
                    Batch: <span className="font-mono text-gray-700">{selected.batch_id}</span>
                  </p>
                </div>
                <button onClick={() => setSelected(null)} className="text-gray-500 hover:text-gray-700 text-2xl">✕</button>
              </div>
              <div className="p-4 overflow-y-auto flex-1 space-y-6">
                {/* State Card */}
                <div className="bg-gray-50 rounded-lg p-4">
                  <h3 className="text-lg font-semibold mb-2">Readiness State</h3>
                  <div className="flex items-center gap-4">
                    <span className={`px-4 py-2 text-lg font-semibold rounded ${stateColor(selected.state)}`}>
                      {stateLabel(selected.state)}
                    </span>
                    <span className="text-gray-500">Computed at {formatDate(selected.created_at)}</span>
                  </div>
                  <p className="mt-2 text-gray-600">{selected.explanation}</p>
                </div>

                {/* Metrics */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                  <div className="bg-white p-4 rounded-lg border">
                    <p className="text-sm text-gray-500">Blocking Conflicts</p>
                    <p className="text-3xl font-bold text-red-600">{selected.blocking_conflict_count}</p>
                  </div>
                  <div className="bg-white p-4 rounded-lg border">
                    <p className="text-sm text-gray-500">Open Conflicts</p>
                    <p className="text-3xl font-bold text-orange-600">{selected.open_conflict_count}</p>
                  </div>
                  <div className="bg-white p-4 rounded-lg border">
                    <p className="text-sm text-gray-500">Accepted Claims</p>
                    <p className="text-3xl font-bold text-green-600">{selected.accepted_claim_count}</p>
                  </div>
                  <div className="bg-white p-4 rounded-lg border">
                    <p className="text-sm text-gray-500">Pending Claims</p>
                    <p className="text-3xl font-bold text-yellow-600">{selected.pending_claim_count}</p>
                  </div>
                </div>

                {/* Assumptions */}
                {selected.assumptions && selected.assumptions.length > 0 && (
                  <div>
                    <h3 className="text-lg font-semibold mb-2">Assumptions</h3>
                    <ul className="space-y-2">
                      {selected.assumptions.map((a, i) => (
                        <li key={i} className="flex items-start gap-2 text-sm">
                          <span className="text-blue-600">#{i + 1}</span>
                          <span className="text-gray-700">{a}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {/* Close */}
                <div className="pt-4 border-t flex justify-end">
                  <button onClick={() => setSelected(null)} className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700">
                    Close
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

export default function ReadinessPage() {
  return (
    <Suspense fallback={<div className="p-8 font-mono text-sm text-[#666666]">Loading readiness assessments...</div>}>
      <ReadinessContent />
    </Suspense>
  )
}