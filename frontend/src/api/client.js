import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 120000,
})

// ── Upload ────────────────────────────────────────────────────────────────────

export const uploadPDF = (file, onProgress) => {
  const form = new FormData()
  form.append('file', file)
  return api.post('/upload', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: (e) => {
      if (onProgress && e.total) onProgress(Math.round((e.loaded * 100) / e.total))
    },
  })
}

export const getFiles = () => api.get('/files')
export const activateFile = (fileId) => api.post(`/files/${fileId}/activate`)
export const resetSession = () => api.delete('/session')

// ── Chat ──────────────────────────────────────────────────────────────────────

export const sendChat = (query, fileId) =>
  api.post('/chat', { query, file_id: fileId })

export const getChatHistory = () => api.get('/chat/history')
export const clearChatHistory = () => api.delete('/chat/history')

/**
 * Stream chat response via fetch + ReadableStream.
 * onToken(token, isDirect) — called for each streamed token
 * onDone()                 — called when streaming completes
 * onError(err)             — called on error
 */
export const streamChat = async (query, fileId, onToken, onDone, onError) => {
  try {
    const response = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, file_id: fileId }),
    })

    const reader  = response.body.getReader()
    const decoder = new TextDecoder()

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      const text  = decoder.decode(value, { stream: true })
      const lines = text.split('\n').filter((l) => l.startsWith('data: '))

      for (const line of lines) {
        try {
          const data = JSON.parse(line.slice(6))
          if (data.token) onToken(data.token, !!data.direct)
          if (data.done) {
            onDone()
            return
          }
        } catch (_) {
          // ignore malformed JSON
        }
      }
    }
    onDone()
  } catch (err) {
    if (onError) onError(err)
  }
}

// ── Analytics ─────────────────────────────────────────────────────────────────

export const getAnalytics     = ()       => api.get('/analytics')
export const getAnalyticsById = (fileId) => api.get(`/analytics/${fileId}`)

// ── Reconciliation ────────────────────────────────────────────────────────────

export const getAllReconciliations   = ()       => api.get('/reconciliation')
export const getReconciliationByPeriod = (period) =>
  api.get(`/reconciliation/${encodeURIComponent(period)}`)
export const computeReconciliation  = (gstr1Id, gstr3bId) =>
  api.post('/reconciliation/compute', { gstr1_file_id: gstr1Id, gstr3b_file_id: gstr3bId })

// ── Export ────────────────────────────────────────────────────────────────────

export const exportExcel = (fileId) => window.open(`/api/export/excel/${fileId}`, '_blank')
export const exportPDF   = (fileId) => window.open(`/api/export/pdf/${fileId}`,   '_blank')
export const exportActiveExcel = () => window.open('/api/export/active/excel', '_blank')
export const exportActivePDF   = () => window.open('/api/export/active/pdf',   '_blank')

// MOM export — format: 'raw' | 'l' | 'cr', optional annualFileId
export const exportMOMExcel = (fmt = 'raw', annualFileId = null) => {
  const params = new URLSearchParams({ format: fmt })
  if (annualFileId) params.append('annual_file_id', annualFileId)
  window.open(`/api/export/mom/excel?${params}`, '_blank')
}

// GSTR-3B MOM export — 52-column format matching official reference
export const exportMOM3BExcel = (fmt = 'raw', annualFileId = null) => {
  const params = new URLSearchParams({ format: fmt })
  if (annualFileId) params.append('annual_file_id', annualFileId)
  window.open(`/api/export/mom-3b/excel?${params}`, '_blank')
}

// GSTR-9 export — exact reference format (one sheet per year)
export const exportMOM9Excel = (fmt = 'raw') => {
  const params = new URLSearchParams({ format: fmt })
  window.open(`/api/export/mom-9/excel?${params}`, '_blank')
}

// ── GSTR-2B Compiler ─────────────────────────────────────────────────────────

/**
 * Upload multiple GSTR-2B .xlsx files and receive the compiled workbook.
 * Returns a Blob URL the caller can use to trigger a download.
 */
export const compileGSTR2B = async (files, onProgress) => {
  const form = new FormData()
  files.forEach((f) => form.append('files', f))

  const response = await fetch('/api/gstr2b/compile', {
    method: 'POST',
    body: form,
  })

  if (!response.ok) {
    const err = await response.json().catch(() => ({ error: response.statusText }))
    throw new Error(err.error || 'Compilation failed')
  }

  const blob = await response.blob()
  const url  = URL.createObjectURL(blob)

  // Extract filename from Content-Disposition header
  const cd   = response.headers.get('Content-Disposition') || ''
  const match = cd.match(/filename="?([^"]+)"?/)
  const name  = match ? match[1] : 'GSTR2B_Compiled.xlsx'

  return { url, name }
}

// ── GSTR-2A Compiler ─────────────────────────────────────────────────────────

/**
 * Upload multiple GSTR-2A .xlsx files and receive the compiled workbook.
 * Returns a Blob URL the caller can use to trigger a download.
 */
export const compileGSTR2A = async (files, onProgress) => {
  const form = new FormData()
  files.forEach((f) => form.append('files', f))

  const response = await fetch('/api/gstr2a/compile', {
    method: 'POST',
    body: form,
  })

  if (!response.ok) {
    const err = await response.json().catch(() => ({ error: response.statusText }))
    throw new Error(err.error || 'Compilation failed')
  }

  const blob = await response.blob()
  const url  = URL.createObjectURL(blob)

  const cd    = response.headers.get('Content-Disposition') || ''
  const match = cd.match(/filename="?([^"]+)"?/)
  const name  = match ? match[1] : 'GSTR2A_Compiled.xlsx'

  return { url, name }
}

// ── Risk Intelligence ─────────────────────────────────────────────────────────

export const getRiskRatios   = () => api.get('/intelligence/ratios')
export const getAnomalies    = () => api.get('/intelligence/anomalies')
export const exportRiskExcel = () => window.open('/api/export/risk/excel', '_blank')
export const exportAnomaliesExcel = () => window.open('/api/export/anomalies/excel', '_blank')

export default api
