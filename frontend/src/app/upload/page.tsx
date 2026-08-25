'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000/api/v1'

export default function UploadPage() {
  const [file, setFile] = useState<File | null>(null)
  const [workspaceId, setWorkspaceId] = useState('')
  const [sourceSystem, setSourceSystem] = useState('unknown')
  const [uploading, setUploading] = useState(false)
  const [result, setResult] = useState<any>(null)
  const [error, setError] = useState('')
  const router = useRouter()

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!file || !workspaceId) {
      setError('File and workspace ID are required')
      return
    }

    setUploading(true)
    setError('')

    const formData = new FormData()
    formData.append('workspace_id', workspaceId)
    formData.append('file', file)
    formData.append('source_system_hint', sourceSystem)

    try {
      const res = await fetch(`${API_BASE}/sources/upload`, {
        method: 'POST',
        body: formData,
      })

      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail || 'Upload failed')
      }

      const data = await res.json()
      setResult(data)
    } catch (err: any) {
      setError(err.message)
    } finally {
      setUploading(false)
    }
  }

  return (
    <main className="min-h-screen p-8">
      <h1 className="text-3xl font-bold mb-4">Upload Source File</h1>
      <p className="mb-8 text-gray-600">Upload CSV or XLSX files for validation, profiling, and evidence extraction.</p>

      <form onSubmit={handleSubmit} className="max-w-lg space-y-4">
        <div>
          <label className="block text-sm font-medium mb-1">Workspace ID</label>
          <input
            type="text"
            value={workspaceId}
            onChange={(e) => setWorkspaceId(e.target.value)}
            className="w-full border rounded px-3 py-2"
            placeholder="UUID"
            required
          />
        </div>

        <div>
          <label className="block text-sm font-medium mb-1">Source System</label>
          <select
            value={sourceSystem}
            onChange={(e) => setSourceSystem(e.target.value)}
            className="w-full border rounded px-3 py-2"
          >
            <option value="unknown">Unknown</option>
            <option value="erp">ERP</option>
            <option value="wms">WMS</option>
            <option value="tms">TMS</option>
            <option value="spreadsheet">Spreadsheet</option>
            <option value="manual">Manual</option>
          </select>
        </div>

        <div>
          <label className="block text-sm font-medium mb-1">File</label>
          <input
            type="file"
            accept=".csv,.xlsx"
            onChange={(e) => setFile(e.target.files?.[0] || null)}
            className="w-full border rounded px-3 py-2"
            required
          />
        </div>

        <button
          type="submit"
          disabled={uploading}
          className="bg-blue-600 text-white px-6 py-2 rounded hover:bg-blue-700 disabled:opacity-50"
        >
          {uploading ? 'Uploading...' : 'Upload'}
        </button>
      </form>

      {error && (
        <div className="mt-6 p-4 bg-red-50 border border-red-200 rounded">
          <p className="text-red-800">{error}</p>
        </div>
      )}

      {result && (
        <div className="mt-6 p-4 bg-green-50 border border-green-200 rounded">
          <h2 className="font-semibold mb-2">Upload Successful</h2>
          <dl className="space-y-1 text-sm">
            <div><span className="font-medium">Batch ID:</span> {result.batch_id}</div>
            <div><span className="font-medium">File ID:</span> {result.file_id}</div>
            <div><span className="font-medium">Status:</span> {result.status}</div>
            <div><span className="font-medium">Checksum:</span> {result.checksum}</div>
            <div><span className="font-medium">Duplicate:</span> {result.is_duplicate ? 'Yes' : 'No'}</div>
          </dl>
          <div className="mt-4 flex gap-2">
            <button onClick={() => router.push('/evidence')} className="text-blue-600 hover:underline">View Evidence</button>
            <button onClick={() => router.push('/readiness')} className="text-blue-600 hover:underline">Check Readiness</button>
            <button onClick={() => router.push('/graph')} className="text-blue-600 hover:underline">Open Graph</button>
          </div>
        </div>
      )}
    </main>
  )
}