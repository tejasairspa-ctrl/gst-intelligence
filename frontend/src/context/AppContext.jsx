import React, { createContext, useCallback, useContext, useRef, useState } from 'react'
import {
  uploadPDF, streamChat, getAnalytics, getAnalyticsById,
  activateFile as activateFileAPI,
  getAllReconciliations, computeReconciliation,
  resetSession as resetSessionAPI,
} from '../api/client'

const AppContext = createContext(null)

export function AppProvider({ children }) {
  // Upload state
  const [uploadedFiles, setUploadedFiles]   = useState([])
  const [activeFile, setActiveFileState]    = useState(null)
  const [isUploading, setIsUploading]       = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [filesByPeriod, setFilesByPeriod]   = useState({}) // { period: { gst_type: file_info } }

  // Analytics state
  const [analytics, setAnalytics]           = useState(null)
  const [extractedData, setExtractedData]   = useState(null)
  // Per-file analytics map: { [fileId]: { analytics, extracted_data } }
  const [analyticsById, setAnalyticsById]   = useState({})

  // Reconciliation state
  const [reconciliations, setReconciliations] = useState({}) // { period: recon_data }
  const [activeReconciliation, setActiveReconciliation] = useState(null)

  // Chat state
  const [messages, setMessages]             = useState([])
  const [isStreaming, setIsStreaming]        = useState(false)

  // Panel / UI state
  const [hasDashboard, setHasDashboard]     = useState(false)
  const [parseWarnings, setParseWarnings]   = useState([])
  const [expandedItem, setExpandedItem]     = useState(null) // For double-click expand

  // Annual reference file (for Annual vs MOM comparison row)
  const [annualFileId, setAnnualFileId]     = useState(null)
  const [annualFileId3B, setAnnualFileId3B] = useState(null)

  // ── KPI / MOM mode ─────────────────────────────────────────────────────────
  // Auto-detected on upload: 1 file → kpi, >1 → mom. User can override via toggle.
  const [currentMode, setCurrentModeState]  = useState('kpi')

  const setCurrentMode = useCallback((mode) => {
    console.log('[GST] toggle_clicked:', mode)
    setCurrentModeState(mode)
  }, [])

  const streamAbortRef = useRef(null)

  // ── Helpers ─────────────────────────────────────────────────────────────────

  const _mergePeriodGroups = useCallback((newGroups) => {
    setFilesByPeriod((prev) => {
      const merged = { ...prev }
      for (const [period, types] of Object.entries(newGroups)) {
        merged[period] = { ...(merged[period] || {}), ...types }
      }
      return merged
    })
  }, [])

  // ── Upload ──────────────────────────────────────────────────────────────────

  const handleUpload = useCallback(async (file) => {
    setIsUploading(true)
    setUploadProgress(0)

    try {
      const { data } = await uploadPDF(file, setUploadProgress)

      const fileEntry = {
        id:         data.file_id,
        name:       file.name,
        gst_type:   data.gst_type,
        period:     data.period,
        uploadedAt: new Date().toISOString(),
        status:     data.parse_success ? 'ready' : 'warning',
      }

      setUploadedFiles((prev) => {
        // Avoid duplicate by id
        const exists = prev.find((f) => f.id === fileEntry.id)
        return exists ? prev : [fileEntry, ...prev]
      })

      setActiveFileState(fileEntry)
      setAnalytics(data.analytics)
      setExtractedData(data.extracted_data)
      setParseWarnings(data.parse_warnings || [])
      setHasDashboard(true)

      // Store analytics keyed by file id for MOM aggregation
      setAnalyticsById((prev) => ({
        ...prev,
        [data.file_id]: {
          analytics:      data.analytics,
          extracted_data: data.extracted_data,
        },
      }))

      // Auto-detect mode: 1 file → KPI, multiple → MOM
      setUploadedFiles((prevFiles) => {
        const nextCount = prevFiles.find((f) => f.id === fileEntry.id)
          ? prevFiles.length
          : prevFiles.length + 1
        const detectedMode = nextCount > 1 ? 'mom' : 'kpi'
        console.log('[GST] mode_detected:', detectedMode, '| files_count:', nextCount)
        setCurrentModeState(detectedMode)
        return prevFiles
      })

      // Update period groupings from server response
      if (data.period && data.period !== 'Period not found') {
        _mergePeriodGroups({
          [data.period]: {
            [data.gst_type]: { ...fileEntry, id: data.file_id },
          },
        })
      }

      // Handle reconciliation if triggered
      if (data.reconciliation_triggered && data.reconciliation) {
        setReconciliations((prev) => ({
          ...prev,
          [data.period]: data.reconciliation,
        }))
        setActiveReconciliation(data.reconciliation)
      }

      // Welcome message
      let welcomeText = data.parse_success
        ? `✅ **${data.gst_type}** loaded for **${data.period || 'the selected period'}**.\n\nI've extracted all data and computed analytics. Ask me anything — or check the **Analytics** panel on the right.`
        : `⚠️ File uploaded with warnings:\n${(data.parse_warnings || []).map((w) => `• ${w}`).join('\n')}\n\nSome data may be unavailable. You can still ask questions.`

      if (data.reconciliation_triggered && data.reconciliation?.available) {
        const status = data.reconciliation.summary?.status
        welcomeText += `\n\n🔄 **Auto-reconciliation complete** for ${data.period}:\n`
        if (status === 'MISMATCH') {
          welcomeText += `⚠️ ${data.reconciliation.flags?.length || 0} mismatch(es) found — check the Reconciliation tab.`
        } else {
          welcomeText += `✅ GSTR-1 and GSTR-3B are reconciled within threshold.`
        }
      }

      setMessages((prev) => {
        const welcome = {
          id:        Date.now(),
          role:      'assistant',
          content:   welcomeText,
          timestamp: new Date().toISOString(),
        }
        // Keep history but add welcome at end
        return prev.length === 0 ? [welcome] : [...prev, welcome]
      })

      return data
    } catch (err) {
      const msg = err.response?.data?.error || err.message || 'Upload failed'
      throw new Error(msg)
    } finally {
      setIsUploading(false)
      setUploadProgress(0)
    }
  }, [_mergePeriodGroups])

  // ── Activate file ───────────────────────────────────────────────────────────

  const setActiveFile = useCallback(async (file) => {
    try {
      await activateFileAPI(file.id)
      setActiveFileState(file)
      // Refresh analytics for this file
      const { data } = await getAnalyticsById(file.id)
      if (data?.available) {
        setAnalytics(data.analytics)
        setExtractedData(data.extracted_data)
      }
      // Load reconciliation for this period
      if (file.period) {
        const recon = reconciliations[file.period]
        setActiveReconciliation(recon || null)
      }
    } catch (_) {
      setActiveFileState(file)
    }
  }, [reconciliations])

  // ── Chat ────────────────────────────────────────────────────────────────────

  const sendMessage = useCallback(async (query) => {
    if (!query.trim() || isStreaming) return

    const userMsg = {
      id:        Date.now(),
      role:      'user',
      content:   query,
      timestamp: new Date().toISOString(),
    }
    const assistantMsg = {
      id:        Date.now() + 1,
      role:      'assistant',
      content:   '',
      streaming: true,
      isDirect:  false,
      timestamp: new Date().toISOString(),
    }

    setMessages((prev) => [...prev, userMsg, assistantMsg])
    setIsStreaming(true)

    await streamChat(
      query,
      activeFile?.id,
      // onToken
      (token, isDirect) => {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantMsg.id
              ? { ...m, content: m.content + token, isDirect }
              : m
          )
        )
      },
      // onDone
      () => {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantMsg.id ? { ...m, streaming: false } : m
          )
        )
        setIsStreaming(false)
      },
      // onError
      (err) => {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantMsg.id
              ? { ...m, content: `⚠️ Error: ${err.message}`, streaming: false }
              : m
          )
        )
        setIsStreaming(false)
      }
    )
  }, [activeFile, isStreaming])

  const clearChat = useCallback(() => setMessages([]), [])

  // ── Refresh analytics ───────────────────────────────────────────────────────

  const refreshAnalytics = useCallback(async () => {
    try {
      const { data } = await getAnalytics()
      if (data.available) {
        setAnalytics(data.analytics)
        setExtractedData(data.extracted_data)
      }
    } catch (_) {}
  }, [])

  // ── Reconciliation ──────────────────────────────────────────────────────────

  const triggerReconciliation = useCallback(async (gstr1FileId, gstr3bFileId) => {
    try {
      const { data } = await computeReconciliation(gstr1FileId, gstr3bFileId)
      if (data.reconciliation) {
        setReconciliations((prev) => ({
          ...prev,
          [data.period]: data.reconciliation,
        }))
        setActiveReconciliation(data.reconciliation)
      }
      return data.reconciliation
    } catch (err) {
      console.error('Reconciliation failed:', err)
      return null
    }
  }, [])

  const loadAllReconciliations = useCallback(async () => {
    try {
      const { data } = await getAllReconciliations()
      if (data.reconciliations) {
        setReconciliations(data.reconciliations)
      }
      if (data.files_by_period) {
        setFilesByPeriod(data.files_by_period)
      }
    } catch (_) {}
  }, [])

  // ── New Session — clears everything ────────────────────────────────────────

  const clearSession = useCallback(async () => {
    try { await resetSessionAPI() } catch (_) {}
    // Reset all frontend state
    setUploadedFiles([])
    setActiveFileState(null)
    setAnalytics(null)
    setExtractedData(null)
    setAnalyticsById({})
    setFilesByPeriod({})
    setReconciliations({})
    setActiveReconciliation(null)
    setMessages([])
    setHasDashboard(false)
    setParseWarnings([])
    setExpandedItem(null)
    setAnnualFileId(null)
    setCurrentModeState('kpi')
  }, [])

  // ── Expanded view (double-click) ─────────────────────────────────────────────

  const openExpanded = useCallback((item) => setExpandedItem(item), [])
  const closeExpanded = useCallback(() => setExpandedItem(null), [])

  const value = {
    // Upload
    uploadedFiles,
    activeFile,
    isUploading,
    uploadProgress,
    handleUpload,
    setActiveFile,
    filesByPeriod,
    // Analytics
    analytics,
    extractedData,
    analyticsById,
    refreshAnalytics,
    // Reconciliation
    reconciliations,
    activeReconciliation,
    triggerReconciliation,
    loadAllReconciliations,
    // Chat
    messages,
    isStreaming,
    sendMessage,
    clearChat,
    // UI
    hasDashboard,
    parseWarnings,
    expandedItem,
    openExpanded,
    closeExpanded,
    // Annual reference
    annualFileId,
    setAnnualFileId,
    annualFileId3B,
    setAnnualFileId3B,
    // Mode (KPI / MOM)
    currentMode,
    setCurrentMode,
    // Session
    clearSession,
  }

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>
}

export const useApp = () => {
  const ctx = useContext(AppContext)
  if (!ctx) throw new Error('useApp must be used inside AppProvider')
  return ctx
}
