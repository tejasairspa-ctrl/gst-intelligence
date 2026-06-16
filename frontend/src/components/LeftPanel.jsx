/**
 * LeftPanel — File list with period groupings + chat history + reports.
 */
import React, { useState } from 'react'
import {
  FileText, MessageSquare, BarChart2, Trash2,
  CheckCircle2, AlertTriangle, Clock, ChevronDown, ChevronRight,
  GitCompare, RotateCcw,
} from 'lucide-react'
import { useApp } from '../context/AppContext'
import { activateFile as activateFileAPI, exportActiveExcel, exportActivePDF } from '../api/client'
import { useNavigate } from 'react-router-dom'

function StatusIcon({ status }) {
  if (status === 'ready')   return <CheckCircle2 className="w-3 h-3 text-emerald-400" />
  if (status === 'warning') return <AlertTriangle className="w-3 h-3 text-amber-400" />
  return <Clock className="w-3 h-3 text-slate-500" />
}

// ── Period group ──────────────────────────────────────────────────────────────
function PeriodGroup({ period, typeMap, activeFile, onActivate, reconciliation }) {
  const [expanded, setExpanded] = useState(true)
  const hasRecon = reconciliation?.available

  return (
    <div className="mb-2">
      {/* Period header */}
      <button
        onClick={() => setExpanded((e) => !e)}
        className="w-full flex items-center justify-between px-2 py-1.5 text-left rounded-lg hover:bg-slate-800/40 transition-colors group"
      >
        <div className="flex items-center gap-1.5">
          {expanded
            ? <ChevronDown className="w-3 h-3 text-slate-600 flex-shrink-0" />
            : <ChevronRight className="w-3 h-3 text-slate-600 flex-shrink-0" />
          }
          <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider truncate">
            {period}
          </span>
        </div>
        {hasRecon && (
          <span className={`text-[9px] px-1.5 py-0.5 rounded-full border flex-shrink-0 ${
            reconciliation.summary?.status === 'RECONCILED'
              ? 'text-emerald-400 border-emerald-500/30 bg-emerald-500/10'
              : 'text-red-400 border-red-500/30 bg-red-500/10'
          }`}>
            {reconciliation.summary?.status === 'RECONCILED' ? '✓ Recon' : '⚠ Mismatch'}
          </span>
        )}
      </button>

      {expanded && (
        <div className="ml-2 space-y-1 mt-0.5">
          {Object.entries(typeMap).map(([gstType, fileInfo]) => {
            if (gstType === 'UNKNOWN') return null
            const isActive = activeFile?.id === fileInfo.id
            return (
              <button
                key={gstType}
                onClick={() => onActivate(fileInfo)}
                className={`w-full text-left px-3 py-2 rounded-lg transition-all ${
                  isActive
                    ? 'bg-blue-600/20 border border-blue-500/40 text-white'
                    : 'hover:bg-slate-800/60 text-slate-300 border border-transparent'
                }`}
              >
                <div className="flex items-center gap-2">
                  <FileText className="w-3 h-3 flex-shrink-0 text-blue-400" />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5">
                      <span className="text-[11px] font-medium">{gstType}</span>
                      <StatusIcon status={fileInfo.status} />
                    </div>
                    <p className="text-[9px] text-slate-500 truncate">{fileInfo.filename}</p>
                  </div>
                </div>
              </button>
            )
          })}

          {/* Reconciliation link */}
          {hasRecon && (
            <div className={`ml-1 px-2 py-1.5 rounded-lg border ${
              reconciliation.summary?.status === 'RECONCILED'
                ? 'bg-emerald-500/5 border-emerald-500/15'
                : 'bg-red-500/5 border-red-500/15'
            }`}>
              <div className="flex items-center gap-1.5">
                <GitCompare className="w-3 h-3 text-slate-500 flex-shrink-0" />
                <div>
                  <p className="text-[10px] text-slate-500 font-medium">Reconciliation</p>
                  <p className={`text-[9px] ${
                    reconciliation.summary?.status === 'RECONCILED'
                      ? 'text-emerald-500'
                      : 'text-red-500'
                  }`}>
                    {reconciliation.summary?.flagged_items || 0} flag(s) · {reconciliation.summary?.total_items || 0} items
                  </p>
                </div>
              </div>
            </div>
          )}

          {/* Missing counterpart hint */}
          {Object.keys(typeMap).filter((t) => t !== 'UNKNOWN').length === 1 && (
            (() => {
              const existingType = Object.keys(typeMap).find((t) => t !== 'UNKNOWN')
              const missing = existingType === 'GSTR-1' ? 'GSTR-3B' : existingType === 'GSTR-3B' ? 'GSTR-1' : null
              return missing ? (
                <div className="ml-1 px-2 py-1 rounded-lg border border-dashed border-slate-700/40">
                  <p className="text-[9px] text-slate-600 text-center">
                    Upload {missing} to enable reconciliation
                  </p>
                </div>
              ) : null
            })()
          )}
        </div>
      )}
    </div>
  )
}

// ── Main LeftPanel ────────────────────────────────────────────────────────────
export default function LeftPanel() {
  const {
    uploadedFiles,
    activeFile,
    setActiveFile,
    clearChat,
    messages,
    filesByPeriod,
    reconciliations,
    clearSession,
  } = useApp()
  const [confirmClear, setConfirmClear] = useState(false)

  const handleNewSession = async () => {
    if (!confirmClear) { setConfirmClear(true); return }
    await clearSession()
    setConfirmClear(false)
  }
  const navigate  = useNavigate()
  const [activeTab, setActiveTab] = useState('files')

  const handleActivate = (file) => setActiveFile(file)

  // Determine whether we should show period groups or flat list
  const periodKeys = Object.keys(filesByPeriod).filter(
    (p) => p !== 'Period not found' && p !== 'Unknown Period'
  )
  const usePeriodGroups = periodKeys.length > 0

  return (
    <aside className="flex flex-col h-full bg-slate-950 border-r border-slate-800/60">
      {/* Logo */}
      <div className="px-4 py-4 border-b border-slate-800/60">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-blue-600 flex items-center justify-center text-sm font-bold text-white">G</div>
          <div>
            <p className="text-white font-semibold text-sm leading-tight">GST Intelligence</p>
            <p className="text-slate-500 text-xs">AI Analytics Platform</p>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-slate-800/60">
        {[
          { id: 'files',   icon: FileText,     label: 'Files'   },
          { id: 'history', icon: MessageSquare, label: 'History' },
          { id: 'reports', icon: BarChart2,     label: 'Reports' },
        ].map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`flex-1 flex flex-col items-center gap-1 py-2.5 text-xs transition-colors ${
              activeTab === tab.id
                ? 'text-blue-400 border-b-2 border-blue-400'
                : 'text-slate-500 hover:text-slate-300'
            }`}
          >
            <tab.icon className="w-3.5 h-3.5" />
            {tab.label}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-3">

        {/* Files tab */}
        {activeTab === 'files' && (
          <>
            {/* New Session button — shown when files are present */}
            {uploadedFiles.length > 0 && (
              <div className="mb-3">
                <button
                  onClick={handleNewSession}
                  onBlur={() => setConfirmClear(false)}
                  className={`w-full flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-xs font-semibold transition-all border ${
                    confirmClear
                      ? 'bg-red-500/20 border-red-500/50 text-red-400 animate-pulse'
                      : 'bg-slate-800/60 border-slate-700/60 text-slate-400 hover:bg-red-500/10 hover:border-red-500/30 hover:text-red-400'
                  }`}
                >
                  <RotateCcw className="w-3 h-3" />
                  {confirmClear ? 'Click again to confirm clear' : 'New Session — Clear All Files'}
                </button>
              </div>
            )}

            {uploadedFiles.length === 0 ? (
              <div className="text-center py-8 text-slate-600 text-xs">
                <FileText className="w-6 h-6 mx-auto mb-2 opacity-40" />
                No files uploaded yet
              </div>
            ) : usePeriodGroups ? (
              // Period-grouped view
              <div>
                {periodKeys.map((period) => (
                  <PeriodGroup
                    key={period}
                    period={period}
                    typeMap={filesByPeriod[period] || {}}
                    activeFile={activeFile}
                    onActivate={handleActivate}
                    reconciliation={reconciliations[period]}
                  />
                ))}

                {/* Files with unknown period */}
                {uploadedFiles
                  .filter((f) => !f.period || f.period === 'Period not found')
                  .map((file) => (
                    <button
                      key={file.id}
                      onClick={() => handleActivate(file)}
                      className={`w-full text-left px-3 py-2.5 rounded-lg transition-all mb-1 ${
                        activeFile?.id === file.id
                          ? 'bg-blue-600/20 border border-blue-500/40 text-white'
                          : 'hover:bg-slate-800/60 text-slate-300 border border-transparent'
                      }`}
                    >
                      <div className="flex items-start gap-2">
                        <FileText className="w-3.5 h-3.5 mt-0.5 flex-shrink-0 text-blue-400" />
                        <div className="min-w-0 flex-1">
                          <p className="text-xs font-medium truncate">{file.name}</p>
                          <div className="flex items-center gap-1.5 mt-0.5">
                            <StatusIcon status={file.status} />
                            <span className="text-[10px] text-slate-500">{file.gst_type}</span>
                          </div>
                        </div>
                      </div>
                    </button>
                  ))}
              </div>
            ) : (
              // Flat list (fallback)
              <div className="space-y-1.5">
                {uploadedFiles.map((file) => (
                  <button
                    key={file.id}
                    onClick={() => handleActivate(file)}
                    className={`w-full text-left px-3 py-2.5 rounded-lg transition-all ${
                      activeFile?.id === file.id
                        ? 'bg-blue-600/20 border border-blue-500/40 text-white'
                        : 'hover:bg-slate-800/60 text-slate-300 border border-transparent'
                    }`}
                  >
                    <div className="flex items-start gap-2">
                      <FileText className="w-3.5 h-3.5 mt-0.5 flex-shrink-0 text-blue-400" />
                      <div className="min-w-0 flex-1">
                        <p className="text-xs font-medium truncate">{file.name}</p>
                        <div className="flex items-center gap-1.5 mt-0.5">
                          <StatusIcon status={file.status} />
                          <span className="text-[10px] text-slate-500">{file.gst_type}</span>
                          {file.period && <span className="text-[10px] text-slate-600">· {file.period}</span>}
                        </div>
                      </div>
                    </div>
                  </button>
                ))}
              </div>
            )}
          </>
        )}

        {/* History tab */}
        {activeTab === 'history' && (
          <div className="space-y-1.5">
            {messages.filter((m) => m.role === 'user').length === 0 ? (
              <div className="text-center py-8 text-slate-600 text-xs">
                <MessageSquare className="w-6 h-6 mx-auto mb-2 opacity-40" />
                No questions asked yet
              </div>
            ) : (
              messages
                .filter((m) => m.role === 'user')
                .map((m) => (
                  <div key={m.id} className="px-3 py-2 rounded-lg bg-slate-800/40 text-xs text-slate-400 truncate">
                    {m.content}
                  </div>
                ))
            )}
            {messages.length > 0 && (
              <button
                onClick={clearChat}
                className="w-full flex items-center gap-2 px-3 py-2 text-xs text-rose-400 hover:bg-rose-500/10 rounded-lg transition-colors mt-2"
              >
                <Trash2 className="w-3.5 h-3.5" /> Clear chat
              </button>
            )}
          </div>
        )}

        {/* Reports tab */}
        {activeTab === 'reports' && (
          <div className="space-y-2">
            {activeFile ? (
              <>
                <p className="section-label px-1 pt-1">Export Active Report</p>
                <button
                  onClick={exportActiveExcel}
                  className="w-full flex items-center gap-2 px-3 py-2.5 rounded-lg bg-emerald-600/15 border border-emerald-600/30 text-emerald-400 text-xs hover:bg-emerald-600/25 transition-colors"
                >
                  <BarChart2 className="w-3.5 h-3.5" /> Download Excel (.xlsx)
                </button>
                <button
                  onClick={exportActivePDF}
                  className="w-full flex items-center gap-2 px-3 py-2.5 rounded-lg bg-blue-600/15 border border-blue-600/30 text-blue-400 text-xs hover:bg-blue-600/25 transition-colors"
                >
                  <FileText className="w-3.5 h-3.5" /> Download CA Report (.pdf)
                </button>
                <button
                  onClick={() => navigate('/report')}
                  className="w-full flex items-center gap-2 px-3 py-2.5 rounded-lg bg-purple-600/15 border border-purple-600/30 text-purple-400 text-xs hover:bg-purple-600/25 transition-colors"
                >
                  <BarChart2 className="w-3.5 h-3.5" /> Full Report View
                </button>
              </>
            ) : (
              <div className="text-center py-8 text-slate-600 text-xs">
                Upload a file to generate reports
              </div>
            )}
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="p-3 border-t border-slate-800/60 text-center">
        <p className="text-[10px] text-slate-700">Audit-safe · No hallucinations</p>
      </div>
    </aside>
  )
}
