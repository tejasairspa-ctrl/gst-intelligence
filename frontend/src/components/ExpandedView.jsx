/**
 * ExpandedView — Center-bottom overlay for double-clicked analytics items.
 * Supports: KPI blocks, Ratio cards, Charts, Insight sections.
 */
import React, { useEffect } from 'react'
import { X, Maximize2, TrendingUp, BarChart2, Scale, Lightbulb, ShieldAlert } from 'lucide-react'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, Legend,
} from 'recharts'
import { useApp } from '../context/AppContext'
import RiskRatiosPanel from './RiskRatiosPanel'

const CHART_COLORS = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4']

function fmt(value, unit = '₹') {
  if (value === null || value === undefined) return 'N/A'
  if (unit === '₹') return `₹${Number(value).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
  if (unit === '%') return `${Number(value).toFixed(2)}%`
  if (unit === 'x') return `${Number(value).toFixed(2)}x`
  return String(value)
}

// ── KPI Expanded ──────────────────────────────────────────────────────────────
function KPIExpanded({ item }) {
  const { kpis = [] } = item
  return (
    <div>
      <h2 className="text-xl font-bold text-white mb-6">Key Performance Indicators</h2>
      <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
        {kpis.map((kpi) => (
          <div
            key={kpi.label}
            className={`p-4 rounded-xl border ${
              kpi.available
                ? 'bg-blue-600/10 border-blue-500/30'
                : 'bg-slate-800/40 border-slate-700/30'
            }`}
          >
            <p className="text-xs text-slate-400 mb-1">{kpi.label}</p>
            {kpi.available ? (
              <p className="text-2xl font-bold text-white font-mono">
                {fmt(kpi.value, kpi.unit)}
              </p>
            ) : (
              <p className="text-sm text-slate-600 italic">Not available</p>
            )}
            {kpi.note && <p className="text-[10px] text-slate-500 mt-1">{kpi.note}</p>}
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Ratio Expanded ────────────────────────────────────────────────────────────
function RatioExpanded({ item }) {
  const { ratios = [] } = item
  return (
    <div>
      <h2 className="text-xl font-bold text-white mb-6">Ratio Analysis</h2>
      <div className="space-y-4">
        {ratios.map((r) => (
          <div
            key={r.name}
            className={`p-4 rounded-xl border ${
              r.available
                ? 'bg-slate-800/60 border-slate-700/50'
                : 'bg-slate-900/40 border-slate-800/30'
            }`}
          >
            <div className="flex items-center justify-between mb-2">
              <p className="text-sm text-slate-300 font-medium">{r.name}</p>
              {r.available && r.value !== null ? (
                <span className="text-2xl font-bold text-white font-mono">
                  {fmt(r.value, r.unit)}
                </span>
              ) : (
                <span className="text-sm text-slate-600 italic">Not available</span>
              )}
            </div>
            {r.benchmark && (
              <p className="text-xs text-slate-500">
                <span className="text-slate-400 font-medium">Benchmark: </span>{r.benchmark}
              </p>
            )}
            {r.interpretation && (
              <p className="text-xs text-slate-400 mt-1">{r.interpretation}</p>
            )}
            {/* Visual bar for percentage ratios */}
            {r.available && r.unit === '%' && r.value !== null && (
              <div className="mt-3 bg-slate-700/40 rounded-full h-2">
                <div
                  className="h-2 rounded-full bg-blue-500 transition-all duration-700"
                  style={{ width: `${Math.min(r.value, 100)}%` }}
                />
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Chart Expanded ────────────────────────────────────────────────────────────
function ChartExpanded({ item }) {
  const { charts = {} } = item
  const taxDist     = charts.tax_distribution  || []
  const itcBreak    = charts.itc_breakdown     || []
  const salesBreak  = charts.sales_breakdown   || []

  const validData = (arr) => arr.filter((d) => d.value !== null && d.value > 0)

  return (
    <div>
      <h2 className="text-xl font-bold text-white mb-6">Chart Analysis</h2>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {validData(taxDist).length > 0 && (
          <div className="bg-slate-800/40 rounded-xl p-4 border border-slate-700/40">
            <p className="text-sm text-slate-400 mb-4 font-medium">Tax Distribution</p>
            <ResponsiveContainer width="100%" height={220}>
              <PieChart>
                <Pie
                  data={validData(taxDist)}
                  dataKey="value"
                  nameKey="label"
                  cx="50%"
                  cy="50%"
                  outerRadius={80}
                  label={({ label, percent }) => `${label}: ${(percent * 100).toFixed(1)}%`}
                  labelLine={false}
                >
                  {validData(taxDist).map((_, i) => (
                    <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip formatter={(v) => `₹${v.toLocaleString('en-IN')}`} />
                <Legend />
              </PieChart>
            </ResponsiveContainer>
          </div>
        )}

        {validData(salesBreak).length > 0 && (
          <div className="bg-slate-800/40 rounded-xl p-4 border border-slate-700/40">
            <p className="text-sm text-slate-400 mb-4 font-medium">Sales Breakdown</p>
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={validData(salesBreak)}>
                <XAxis dataKey="label" tick={{ fill: '#94a3b8', fontSize: 11 }} />
                <YAxis tick={{ fill: '#94a3b8', fontSize: 10 }} tickFormatter={(v) => `₹${(v / 100000).toFixed(0)}L`} />
                <Tooltip formatter={(v) => [`₹${v.toLocaleString('en-IN')}`, 'Value']} />
                <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                  {validData(salesBreak).map((_, i) => (
                    <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}

        {validData(itcBreak).length > 0 && (
          <div className="bg-slate-800/40 rounded-xl p-4 border border-slate-700/40 md:col-span-2">
            <p className="text-sm text-slate-400 mb-4 font-medium">ITC Breakdown</p>
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={validData(itcBreak)} layout="vertical">
                <XAxis type="number" tick={{ fill: '#94a3b8', fontSize: 10 }} tickFormatter={(v) => `₹${(v / 100000).toFixed(0)}L`} />
                <YAxis type="category" dataKey="label" tick={{ fill: '#94a3b8', fontSize: 11 }} width={110} />
                <Tooltip formatter={(v) => [`₹${v.toLocaleString('en-IN')}`, 'Value']} />
                <Bar dataKey="value" radius={[0, 4, 4, 0]}>
                  {validData(itcBreak).map((_, i) => (
                    <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Insights Expanded ─────────────────────────────────────────────────────────
function InsightsExpanded({ item }) {
  const { insights = [] } = item
  return (
    <div>
      <h2 className="text-xl font-bold text-white mb-6">Key Insights & Observations</h2>
      <div className="space-y-4">
        {insights.map((ins, i) => (
          <div
            key={i}
            className="flex gap-4 p-4 bg-blue-600/8 border border-blue-600/20 rounded-xl"
          >
            <span className="flex-shrink-0 w-8 h-8 rounded-full bg-blue-600/20 text-blue-400 font-bold text-sm flex items-center justify-center">
              {i + 1}
            </span>
            <p className="text-sm text-slate-300 leading-relaxed">{ins}</p>
          </div>
        ))}
        {insights.length === 0 && (
          <p className="text-slate-500 text-sm text-center py-8">No insights available</p>
        )}
      </div>
    </div>
  )
}

// ── Risk Expanded ─────────────────────────────────────────────────────────────
function RiskExpanded() {
  const { uploadedFiles } = useApp()
  return (
    <div>
      <h2 className="text-xl font-bold text-white mb-4">Risk Ratios &amp; Intelligence</h2>
      <RiskRatiosPanel uploadedFiles={uploadedFiles || []} expanded />
    </div>
  )
}

// ── Main ExpandedView ─────────────────────────────────────────────────────────
export default function ExpandedView() {
  const { expandedItem, closeExpanded } = useApp()

  useEffect(() => {
    const handler = (e) => {
      if (e.key === 'Escape') closeExpanded()
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [closeExpanded])

  if (!expandedItem) return null

  const renderContent = () => {
    switch (expandedItem.type) {
      case 'kpis':     return <KPIExpanded item={expandedItem} />
      case 'ratios':   return <RatioExpanded item={expandedItem} />
      case 'charts':   return <ChartExpanded item={expandedItem} />
      case 'insights': return <InsightsExpanded item={expandedItem} />
      case 'risk':     return <RiskExpanded />
      default:         return <div className="text-slate-400">No content</div>
    }
  }

  const icons = {
    kpis:     BarChart2,
    ratios:   Scale,
    charts:   TrendingUp,
    insights: Lightbulb,
    risk:     ShieldAlert,
  }
  const Icon = icons[expandedItem.type] || Maximize2

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/60 backdrop-blur-sm z-40 animate-fade-in"
        onClick={closeExpanded}
      />

      {/* Expanded panel — center-bottom */}
      <div className="fixed bottom-0 left-0 right-0 z-50 flex justify-center px-4 pb-4 pointer-events-none">
        <div
          className="w-full bg-slate-900 border border-slate-700/60 rounded-2xl shadow-2xl
                     pointer-events-auto overflow-hidden"
          style={{
            maxWidth: expandedItem?.type === 'risk' ? '90vw' : '64rem',
            maxHeight: expandedItem?.type === 'risk' ? '88vh' : '70vh',
            animation: 'slideUpExpand 0.3s cubic-bezier(0.16, 1, 0.3, 1)',
          }}
        >
          {/* Header */}
          <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800/60 bg-slate-900/90">
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-lg bg-blue-600/20 flex items-center justify-center">
                <Icon className="w-4 h-4 text-blue-400" />
              </div>
              <div>
                <p className="text-sm font-semibold text-white capitalize">
                  {expandedItem.type} — Expanded View
                </p>
                <p className="text-[10px] text-slate-500">Double-click to collapse · ESC to close</p>
              </div>
            </div>
            <button
              onClick={closeExpanded}
              className="w-8 h-8 flex items-center justify-center rounded-lg hover:bg-slate-800 text-slate-500 hover:text-white transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          {/* Content */}
          <div className="overflow-y-auto p-6" style={{ maxHeight: expandedItem?.type === 'risk' ? 'calc(88vh - 72px)' : 'calc(70vh - 72px)' }}>
            {renderContent()}
          </div>
        </div>
      </div>

      <style>{`
        @keyframes slideUpExpand {
          from { transform: translateY(100%); opacity: 0; }
          to   { transform: translateY(0);    opacity: 1; }
        }
        @keyframes fadeIn {
          from { opacity: 0; }
          to   { opacity: 1; }
        }
        .animate-fade-in { animation: fadeIn 0.2s ease; }
      `}</style>
    </>
  )
}
