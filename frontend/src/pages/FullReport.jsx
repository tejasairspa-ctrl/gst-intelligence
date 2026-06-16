import React from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowLeft, FileSpreadsheet, FileText, AlertTriangle } from 'lucide-react'
import { useApp } from '../context/AppContext'
import { KPIGrid } from '../components/KPICard'
import { TaxDistributionChart, ITCChart, SalesBreakdownChart } from '../components/AnalyticsCharts'
import ReconciliationPanel from '../components/ReconciliationPanel'
import { exportExcel, exportPDF } from '../api/client'

const INR = new Intl.NumberFormat('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const fmtINR = (v) => (v !== null && v !== undefined ? `₹${INR.format(v)}` : 'Not available in document')

export default function FullReport() {
  const navigate = useNavigate()
  const { analytics, extractedData, activeFile, parseWarnings, reconciliations, activeReconciliation } = useApp()
  const recon = activeReconciliation || (activeFile?.period ? reconciliations[activeFile.period] : null)

  if (!analytics || !activeFile) {
    return (
      <div className="min-h-screen bg-slate-950 flex items-center justify-center">
        <div className="text-center space-y-4">
          <p className="text-slate-400">No report data. Upload a GST PDF first.</p>
          <button onClick={() => navigate('/')} className="btn-primary">
            Go to Upload
          </button>
        </div>
      </div>
    )
  }

  const charts   = analytics.charts || {}
  const kpis     = analytics.kpis || []
  const ratios   = analytics.ratios || []
  const insights = analytics.insights || []
  const period   = activeFile.period
  const gstType  = activeFile.gst_type
  const gstin    = extractedData?.gstin
  const entity   = extractedData?.legal_name
  const now      = new Date().toLocaleDateString('en-IN', { day: '2-digit', month: 'long', year: 'numeric' })

  return (
    <div className="min-h-screen bg-slate-950 text-slate-200">
      {/* Top bar */}
      <div className="sticky top-0 z-10 bg-slate-950/90 backdrop-blur border-b border-slate-800/60 px-8 py-4 flex items-center justify-between">
        <button
          onClick={() => navigate('/')}
          className="flex items-center gap-2 text-slate-400 hover:text-white transition-colors text-sm"
        >
          <ArrowLeft className="w-4 h-4" /> Back to Chat
        </button>
        <h1 className="text-white font-semibold">Full GST Report</h1>
        <div className="flex gap-2">
          <button
            onClick={() => exportExcel(activeFile.id)}
            className="flex items-center gap-2 px-3 py-1.5 bg-emerald-600/15 border border-emerald-600/30 text-emerald-400 rounded-lg text-xs hover:bg-emerald-600/25 transition-colors"
          >
            <FileSpreadsheet className="w-3.5 h-3.5" /> Excel
          </button>
          <button
            onClick={() => exportPDF(activeFile.id)}
            className="flex items-center gap-2 px-3 py-1.5 bg-blue-600/15 border border-blue-600/30 text-blue-400 rounded-lg text-xs hover:bg-blue-600/25 transition-colors"
          >
            <FileText className="w-3.5 h-3.5" /> CA Report PDF
          </button>
        </div>
      </div>

      <div className="max-w-6xl mx-auto px-8 py-8 space-y-10">

        {/* Cover section */}
        <div className="glass-card p-8 space-y-4">
          <div className="flex items-start justify-between">
            <div>
              <p className="text-xs text-blue-400 font-semibold uppercase tracking-wider mb-1">GST Intelligence Report</p>
              <h2 className="text-3xl font-bold text-white">{gstType}</h2>
              <p className="text-slate-400 text-lg mt-1">{period || 'Selected Period'}</p>
            </div>
            <div className="text-right text-xs text-slate-500 space-y-1">
              <p>Generated: {now}</p>
              <p className="text-[10px] bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 px-2 py-0.5 rounded-full">
                ✓ Audit-Safe Report
              </p>
            </div>
          </div>

          <div className="grid grid-cols-3 gap-4 pt-4 border-t border-slate-800">
            {[
              { label: 'GSTIN',       value: gstin  || 'Not found in document' },
              { label: 'Entity',      value: entity || 'Not found in document' },
              { label: 'Form Type',   value: gstType },
            ].map((item) => (
              <div key={item.label}>
                <p className="text-xs text-slate-600 uppercase tracking-wider">{item.label}</p>
                <p className="text-sm text-white font-medium mt-0.5">{item.value}</p>
              </div>
            ))}
          </div>

          {parseWarnings.length > 0 && (
            <div className="flex items-start gap-2 px-4 py-3 bg-amber-500/8 border border-amber-500/20 rounded-lg">
              <AlertTriangle className="w-4 h-4 text-amber-400 flex-shrink-0 mt-0.5" />
              <div className="text-xs text-amber-400/80 space-y-1">
                {parseWarnings.map((w, i) => <p key={i}>{w}</p>)}
              </div>
            </div>
          )}
        </div>

        {/* Section 1: KPIs */}
        <Section title="1. Key Performance Indicators" subtitle="Computed from extracted document data only">
          <div className="grid grid-cols-3 gap-3 lg:grid-cols-4">
            {kpis.map((k) => (
              <div key={k.label} className="glass-card p-4 space-y-1">
                <p className="text-xs text-slate-500">{k.label}</p>
                {k.available ? (
                  <p className="text-xl font-bold text-white font-mono">
                    {k.unit === '₹' ? fmtINR(k.value) :
                     k.unit === '%' ? `${Number(k.value).toFixed(2)}%` :
                     k.unit === 'x' ? `${Number(k.value).toFixed(2)}x` : k.value}
                  </p>
                ) : (
                  <p className="text-xs text-slate-700 italic">Not available in document</p>
                )}
              </div>
            ))}
          </div>
        </Section>

        {/* Section 2: Charts */}
        <Section title="2. Visual Analysis" subtitle="Charts based on extracted figures">
          <div className="grid grid-cols-3 gap-4">
            <TaxDistributionChart data={charts.tax_distribution} />
            <ITCChart data={charts.itc_breakdown} />
            <SalesBreakdownChart data={charts.sales_breakdown} />
          </div>
        </Section>

        {/* Section 3: Ratio Analysis */}
        <Section title="3. Ratio Analysis" subtitle="Hover over any row for benchmark and interpretation">
          <div className="overflow-hidden rounded-xl border border-slate-800/60">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-slate-900 border-b border-slate-800">
                  <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400">Ratio</th>
                  <th className="text-right px-4 py-3 text-xs font-semibold text-slate-400">Value</th>
                  <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400">Benchmark</th>
                  <th className="text-left px-4 py-3 text-xs font-semibold text-slate-400">Interpretation</th>
                </tr>
              </thead>
              <tbody>
                {ratios.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="text-center py-6 text-slate-700 text-xs">
                      No ratios computable from available data
                    </td>
                  </tr>
                ) : (
                  ratios.map((r, i) => (
                    <tr
                      key={r.name}
                      className={`border-b border-slate-800/40 ${i % 2 === 0 ? '' : 'bg-slate-900/30'}`}
                    >
                      <td className="px-4 py-3 text-slate-300 text-xs">{r.name}</td>
                      <td className="px-4 py-3 text-right font-mono font-semibold text-white text-sm">
                        {r.available && r.value !== null
                          ? `${Number(r.value).toFixed(2)}${r.unit}`
                          : <span className="text-slate-700 italic text-xs font-normal">N/A</span>}
                      </td>
                      <td className="px-4 py-3 text-xs text-slate-500">{r.benchmark || '—'}</td>
                      <td className="px-4 py-3 text-xs text-slate-400">{r.interpretation || '—'}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </Section>

        {/* Section 4: Insights */}
        <Section title="4. Key Findings & Observations" subtitle="System-generated insights from extracted data">
          <div className="space-y-3">
            {insights.map((ins, i) => (
              <div key={i} className="flex gap-3 p-4 glass-card">
                <span className="flex-shrink-0 w-6 h-6 rounded-full bg-blue-600/20 border border-blue-600/30 text-blue-400 text-xs font-bold flex items-center justify-center">
                  {i + 1}
                </span>
                <p className="text-sm text-slate-300 leading-relaxed">{ins}</p>
              </div>
            ))}
          </div>
        </Section>

        {/* Section 5: Reconciliation */}
        {recon && (
          <Section title="5. Reconciliation Analysis" subtitle="GSTR-1 vs GSTR-3B comparison for the same period">
            <div className="glass-card p-6">
              <ReconciliationPanel reconciliation={recon} />
            </div>
          </Section>
        )}

        {/* Section 6: Raw Data */}
        <Section title="6. Extracted Data (Appendix)" subtitle="All fields as directly extracted from the PDF">
          <div className="overflow-hidden rounded-xl border border-slate-800/60">
            <table className="w-full text-xs">
              <thead>
                <tr className="bg-slate-900 border-b border-slate-800">
                  <th className="text-left px-4 py-3 font-semibold text-slate-400">Field</th>
                  <th className="text-right px-4 py-3 font-semibold text-slate-400">Extracted Value</th>
                </tr>
              </thead>
              <tbody>
                {extractedData && Object.entries(extractedData)
                  .filter(([k]) => !k.startsWith('_'))
                  .map(([key, val], i) => (
                    <tr key={key} className={`border-b border-slate-800/30 ${i % 2 === 1 ? 'bg-slate-900/20' : ''}`}>
                      <td className="px-4 py-2.5 text-slate-400 font-mono">{key}</td>
                      <td className="px-4 py-2.5 text-right">
                        {typeof val === 'number'
                          ? <span className="text-white font-mono">{fmtINR(val)}</span>
                          : val !== null
                          ? <span className="text-slate-300">{String(val)}</span>
                          : <span className="text-slate-700 italic">Not available in document</span>}
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </Section>

        {/* Disclaimer */}
        <div className="px-6 py-4 bg-slate-900/40 border border-slate-800/40 rounded-xl text-xs text-slate-600 leading-relaxed">
          <strong className="text-slate-500">Disclaimer:</strong> This report is generated automatically from the uploaded PDF.
          All values shown are extracted directly from the document. Fields marked "Not available in document"
          were not found during extraction. No values have been assumed or estimated.
          Verify with a qualified Chartered Accountant before use for compliance or filing.
        </div>
      </div>
    </div>
  )
}

function Section({ title, subtitle, children }) {
  return (
    <section className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold text-white">{title}</h2>
        {subtitle && <p className="text-xs text-slate-600 mt-0.5">{subtitle}</p>}
      </div>
      {children}
    </section>
  )
}
