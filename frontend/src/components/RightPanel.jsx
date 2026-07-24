/**
 * RightPanel — Analytics sidebar.
 * Tabs: KPIs · Recon · Risk
 * Single-click: view in panel. Click expand button: open overlay.
 */
import React, { useState, useEffect } from 'react'
import {
  BarChart2, AlertTriangle, RefreshCw, Activity,
  Maximize2, GitCompare, ShieldAlert, FileSpreadsheet,
} from 'lucide-react'
import { useApp } from '../context/AppContext'
import { KPIGrid } from './KPICard'
import ReconciliationPanel from './ReconciliationPanel'
import RiskRatiosPanel from './RiskRatiosPanel'
import AnomaliesPanel from './AnomaliesPanel'
import GSTR9Panel from './GSTR9Panel'
import { exportRiskExcel, exportAnomaliesExcel, getAnomalies } from '../api/client'

// ── Expand hint ────────────────────────────────────────────────────────────────
function ExpandHint({ onExpand }) {
  return (
    <button
      onClick={onExpand}
      className="flex items-center gap-1 text-[10px] text-slate-600 hover:text-blue-400
                 transition-colors px-1 py-0.5 rounded"
      title="Expand to full view"
    >
      <Maximize2 className="w-3 h-3" />
      Expand
    </button>
  )
}

// ── Main RightPanel ───────────────────────────────────────────────────────────
export default function RightPanel() {
  const {
    analytics,
    activeFile,
    refreshAnalytics,
    parseWarnings,
    openExpanded,
    activeReconciliation,
    reconciliations,
    uploadedFiles,
  } = useApp()
  const [tab, setTab] = useState('kpis')

  // ── Anomaly scan (for the tab badge only — no popup) ────────────────────────
  const [anomalyData, setAnomalyData] = useState(null)
  const fileCount = uploadedFiles?.length || 0

  useEffect(() => {
    if (fileCount === 0) return
    let cancelled = false
    getAnomalies()
      .then(({ data }) => { if (!cancelled && data?.available) setAnomalyData(data) })
      .catch(() => {})
    return () => { cancelled = true }
  }, [fileCount])

  if (!analytics || !activeFile) {
    return (
      <aside className="flex flex-col h-full border-l border-slate-800/60 items-center justify-center p-6">
        <BarChart2 className="w-10 h-10 text-slate-800 mb-3" />
        <p className="text-slate-700 text-sm text-center">Upload a GST PDF to see live analytics</p>
      </aside>
    )
  }

  const kpis         = analytics.kpis || []
  const recon        = activeReconciliation || reconciliations[activeFile?.period] || null
  const hasRecon     = recon && recon.available
  const isAnnualForm = activeFile?.gst_type === 'GSTR-9' || activeFile?.gst_type === 'GSTR-9C'

  const tabs = isAnnualForm
    ? [
        { id: 'kpis', label: activeFile?.gst_type === 'GSTR-9C' ? 'Recon' : 'Annual', icon: BarChart2 },
        { id: 'risk', label: 'Risk', icon: ShieldAlert },
      ]
    : [
        { id: 'kpis', label: 'KPIs', icon: BarChart2 },
        {
          id: 'recon',
          label: 'Recon',
          icon: GitCompare,
          badge: hasRecon && recon.summary?.flagged_items > 0 ? recon.summary.flagged_items : null,
        },
        { id: 'risk', label: 'Risk', icon: ShieldAlert },
        {
          id: 'anomalies',
          label: 'Anomaly',
          icon: Activity,
          badge: anomalyData?.summary?.high > 0 ? anomalyData.summary.high : null,
        },
      ]

  const handleExpandKPIs = () => openExpanded({ type: 'kpis', kpis })
  const handleExpandRisk = () => openExpanded({ type: 'risk' })

  return (
    <aside className="flex flex-col h-full border-l border-slate-800/60 bg-slate-950/50">
      {/* Header */}
      <div className="px-4 py-3 border-b border-slate-800/60">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-xs font-semibold text-white">{activeFile.gst_type}</p>
            <p className="text-[10px] text-slate-500">{activeFile.period || 'Live Analytics'}</p>
          </div>
          <button
            onClick={refreshAnalytics}
            className="w-7 h-7 flex items-center justify-center rounded-lg hover:bg-slate-800 text-slate-600 hover:text-slate-400 transition-colors"
            title="Refresh analytics"
          >
            <RefreshCw className="w-3.5 h-3.5" />
          </button>
        </div>

        {/* Parse warnings */}
        {parseWarnings.length > 0 && (
          <div className="mt-2 flex items-start gap-1.5 px-2 py-1.5 bg-amber-500/10 border border-amber-500/20 rounded-lg">
            <AlertTriangle className="w-3 h-3 text-amber-400 flex-shrink-0 mt-0.5" />
            <p className="text-[10px] text-amber-400/80 leading-tight">{parseWarnings[0]}</p>
          </div>
        )}

        {/* Reconciliation status badge */}
        {hasRecon && (
          <div
            className={`mt-2 flex items-center gap-1.5 px-2 py-1 rounded-lg border cursor-pointer
            ${recon.summary?.status === 'RECONCILED'
              ? 'bg-emerald-500/8 border-emerald-500/20 text-emerald-400'
              : 'bg-red-500/8 border-red-500/20 text-red-400'
            }`}
            onClick={() => setTab('recon')}
          >
            <GitCompare className="w-3 h-3 flex-shrink-0" />
            <p className="text-[10px] leading-tight">
              {recon.summary?.status === 'RECONCILED'
                ? '✓ Reconciled'
                : `⚠ ${recon.summary?.flagged_items} mismatch(es)`}
              {' — click to view'}
            </p>
          </div>
        )}
      </div>

      {/* Sub-tabs */}
      <div className="flex border-b border-slate-800/60">
        {tabs.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`flex-1 py-2 text-[10px] font-medium transition-colors relative ${
              tab === t.id
                ? 'text-blue-400 border-b-2 border-blue-400'
                : 'text-slate-600 hover:text-slate-400'
            }`}
          >
            {t.label}
            {t.badge && (
              <span className="absolute top-1 right-1 w-3.5 h-3.5 bg-red-500 rounded-full text-[8px] text-white flex items-center justify-center">
                {t.badge}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Panel content */}
      <div className="flex-1 overflow-y-auto p-3 space-y-2">

        {tab === 'kpis' && (
          isAnnualForm ? (
            <GSTR9Panel />
          ) : (
            <>
              <div className="flex items-center justify-between">
                <p className="section-label">Key Performance Indicators</p>
                <ExpandHint onExpand={handleExpandKPIs} />
              </div>
              <div
                onDoubleClick={handleExpandKPIs}
                className="cursor-pointer"
                title="Double-click to expand KPIs"
              >
                <KPIGrid kpis={kpis} compact />
              </div>
            </>
          )
        )}

        {tab === 'recon' && (
          <>
            <p className="section-label">GSTR-1 vs GSTR-3B Reconciliation</p>
            <ReconciliationPanel reconciliation={recon} />
          </>
        )}

        {tab === 'risk' && (
          <>
            <div className="flex items-center justify-between mb-2">
              <p className="section-label">Risk Ratios & Intelligence</p>
              <div className="flex items-center gap-1.5">
                <button
                  onClick={exportRiskExcel}
                  className="flex items-center gap-1 text-[9px] text-emerald-500 hover:text-emerald-400
                             px-1.5 py-0.5 rounded border border-emerald-600/30 bg-emerald-500/10 transition-colors"
                  title="Export risk ratios to Excel"
                >
                  <FileSpreadsheet className="w-3 h-3" /> Export
                </button>
                <ExpandHint onExpand={handleExpandRisk} />
              </div>
            </div>
            <RiskRatiosPanel uploadedFiles={uploadedFiles || []} />
          </>
        )}

        {tab === 'anomalies' && (
          <>
            <div className="flex items-center justify-between mb-2">
              <p className="section-label">Anomaly Detection · MOM & YOY</p>
              <div className="flex items-center gap-1.5">
                <button
                  onClick={exportAnomaliesExcel}
                  className="flex items-center gap-1 text-[9px] text-emerald-500 hover:text-emerald-400
                             px-1.5 py-0.5 rounded border border-emerald-600/30 bg-emerald-500/10 transition-colors"
                  title="Export anomalies to Excel"
                >
                  <FileSpreadsheet className="w-3 h-3" /> Export
                </button>
                <ExpandHint onExpand={() => openExpanded({ type: 'anomalies' })} />
              </div>
            </div>
            <AnomaliesPanel uploadedFiles={uploadedFiles || []} />
          </>
        )}
      </div>
    </aside>
  )
}
