/**
 * RiskRatiosPanel — DGARM-style risk intelligence display.
 * Two tabs:
 *   Ratios — per-period averaged ratios with risk badges
 *   Trend  — FY-level trend table (requires multi-FY uploads)
 */
import React, { useEffect, useState } from 'react'
import { ShieldAlert, ShieldCheck, AlertTriangle, RefreshCw, TrendingUp, TrendingDown, Minus, ChevronDown, ChevronRight } from 'lucide-react'
import { getRiskRatios } from '../api/client'

const LEVEL_STYLE = {
  LOW:     { bg: 'bg-emerald-500/10', border: 'border-emerald-500/30', text: 'text-emerald-400', dot: 'bg-emerald-400' },
  MEDIUM:  { bg: 'bg-amber-500/10',   border: 'border-amber-500/30',   text: 'text-amber-400',   dot: 'bg-amber-400'   },
  HIGH:    { bg: 'bg-red-500/10',     border: 'border-red-500/30',     text: 'text-red-400',     dot: 'bg-red-400'     },
  UNKNOWN: { bg: 'bg-slate-800/40',   border: 'border-slate-700/40',   text: 'text-slate-500',   dot: 'bg-slate-600'   },
}

// ── Ratio card ────────────────────────────────────────────────────────────────

function RiskBadge({ level }) {
  const s = LEVEL_STYLE[level] || LEVEL_STYLE.UNKNOWN
  return (
    <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[9px] font-bold uppercase tracking-wider border ${s.bg} ${s.border} ${s.text}`}>
      <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${s.dot}`} />
      {level}
    </span>
  )
}

function fmtINR(val) {
  if (val === null || val === undefined) return '—'
  const abs = Math.abs(val)
  if (abs >= 1_00_00_000) return `₹${(val / 1_00_00_000).toFixed(2)} Cr`
  if (abs >= 1_00_000)    return `₹${(val / 1_00_000).toFixed(2)} L`
  if (abs >= 1_000)       return `₹${(val / 1_000).toFixed(2)} K`
  return `₹${val.toLocaleString('en-IN', { maximumFractionDigits: 2 })}`
}

function DerivationTable({ components, unit, value, expandedView }) {
  if (!components || components.length === 0) return null
  const textSz = expandedView ? 'text-[11px]' : 'text-[9px]'

  // Find numerator & denominator (first two components)
  const [num, den, ...rest] = components

  return (
    <div className="mt-2 pt-2 border-t border-slate-700/30">
      <p className={`text-slate-500 font-semibold uppercase tracking-wider mb-1.5 ${textSz}`}>
        How Derived
      </p>
      <div className="rounded-md overflow-hidden border border-slate-700/30">
        <table className="w-full border-collapse">
          <thead>
            <tr className="bg-slate-800/60">
              <th className={`text-left px-2 py-1 text-slate-500 font-medium ${textSz}`}>Input</th>
              <th className={`text-left px-2 py-1 text-slate-500 font-medium ${textSz}`}>Source Table</th>
              <th className={`text-right px-2 py-1 text-slate-500 font-medium ${textSz}`}>Value</th>
            </tr>
          </thead>
          <tbody>
            {components.map((c, i) => (
              <tr key={i} className="border-t border-slate-700/20">
                <td className={`px-2 py-1 text-slate-300 font-medium ${textSz}`}>{c.label}</td>
                <td className={`px-2 py-1 text-slate-500 font-mono ${textSz}`}>{c.table}</td>
                <td className={`px-2 py-1 text-right font-mono font-bold text-slate-200 ${textSz}`}>
                  {c.unit === '₹' || c.unit === undefined
                    ? fmtINR(c.value)
                    : c.value !== null && c.value !== undefined ? `${c.value}${c.unit}` : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {/* Computation line */}
      {num && den && value !== null && value !== undefined && (
        <p className={`mt-1.5 text-slate-600 font-mono ${textSz}`}>
          = {fmtINR(num.value)} ÷ {fmtINR(den.value)} × 100
          <span className="ml-2 font-bold text-slate-300">= {value}{unit}</span>
        </p>
      )}
    </div>
  )
}

function PeriodBreakdown({ periods, unit, expandedView }) {
  if (!periods || periods.length === 0) return null
  const textSz = expandedView ? 'text-[11px]' : 'text-[9px]'
  const highCount = periods.filter(p => p.risk_level === 'HIGH').length
  const medCount  = periods.filter(p => p.risk_level === 'MEDIUM').length

  return (
    <div className="mt-2 pt-2 border-t border-slate-700/30">
      <div className="flex items-center justify-between mb-1.5">
        <p className={`text-slate-500 font-semibold uppercase tracking-wider ${textSz}`}>
          Period Breakdown
        </p>
        <div className="flex gap-1">
          {highCount > 0 && (
            <span className="text-[8px] px-1.5 py-0.5 rounded-full bg-red-500/15 border border-red-500/30 text-red-400 font-bold">
              {highCount} HIGH
            </span>
          )}
          {medCount > 0 && (
            <span className="text-[8px] px-1.5 py-0.5 rounded-full bg-amber-500/15 border border-amber-500/30 text-amber-400 font-bold">
              {medCount} MED
            </span>
          )}
          <span className={`text-slate-600 ${textSz}`}>
            total of {periods.filter(p => p.value !== null).length} periods
          </span>
        </div>
      </div>
      <div className="rounded-md overflow-hidden border border-slate-700/30 max-h-48 overflow-y-auto">
        <table className="w-full border-collapse">
          <thead className="sticky top-0 z-10">
            <tr className="bg-slate-800/80">
              <th className={`text-left px-2 py-1 text-slate-500 font-medium ${textSz}`}>Period</th>
              <th className={`text-right px-2 py-1 text-slate-500 font-medium ${textSz}`}>Value</th>
              <th className={`text-center px-2 py-1 text-slate-500 font-medium ${textSz}`}>Risk</th>
            </tr>
          </thead>
          <tbody>
            {periods.map((p, i) => {
              const s = LEVEL_STYLE[p.risk_level] || LEVEL_STYLE.UNKNOWN
              return (
                <tr
                  key={i}
                  className={`border-t border-slate-700/20 ${p.risk_level === 'HIGH' ? 'bg-red-500/5' : p.risk_level === 'MEDIUM' ? 'bg-amber-500/5' : ''}`}
                >
                  <td className={`px-2 py-1 text-slate-400 ${textSz} ${p.anomaly ? 'font-semibold' : ''}`}>
                    {p.anomaly && <AlertTriangle className="w-2.5 h-2.5 inline mr-1 text-amber-400" />}
                    {p.period}
                  </td>
                  <td className={`px-2 py-1 text-right font-mono font-bold ${s.text} ${textSz}`}>
                    {p.value !== null && p.value !== undefined ? `${p.value}${unit}` : '—'}
                  </td>
                  <td className="px-2 py-1 text-center">
                    <RiskBadge level={p.risk_level} />
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function RatioCard({ ratio, expanded: expandedView = false }) {
  const [expanded, setExpanded] = useState(expandedView)
  const s = LEVEL_STYLE[ratio.risk_level] || LEVEL_STYLE.UNKNOWN

  return (
    <div
      className={`rounded-lg border px-3 py-2.5 cursor-pointer transition-all ${s.bg} ${s.border} ${ratio.anomaly ? 'ring-1 ring-amber-500/50' : ''}`}
      onClick={() => setExpanded(e => !e)}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5 flex-wrap">
            {ratio.anomaly && <AlertTriangle className="w-3 h-3 text-amber-400 flex-shrink-0" />}
            <p className={`font-medium leading-tight text-slate-300 ${expandedView ? 'text-xs' : 'text-[11px]'}`}>{ratio.name}</p>
          </div>
          {ratio.dgarm_ref && <p className="text-[9px] text-slate-600 mt-0.5">{ratio.dgarm_ref}</p>}
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          {ratio.available && ratio.value !== null ? (
            <span className={`font-bold font-mono ${s.text} ${expandedView ? 'text-lg' : 'text-sm'}`}>
              {ratio.value}{ratio.unit}
            </span>
          ) : (
            <span className="text-[9px] text-slate-600 italic">N/A</span>
          )}
          <RiskBadge level={ratio.risk_level} />
          {expanded
            ? <ChevronDown  className="w-3 h-3 text-slate-600 flex-shrink-0" />
            : <ChevronRight className="w-3 h-3 text-slate-600 flex-shrink-0" />}
        </div>
      </div>

      {expanded && (
        <div className="mt-2.5 pt-2.5 border-t border-slate-700/40 space-y-2">
          {ratio.formula && (
            <p className={`text-slate-500 ${expandedView ? 'text-[11px]' : 'text-[9px]'}`}>
              <span className="text-slate-400 font-semibold">Formula: </span>
              <span className="font-mono">{ratio.formula}</span>
            </p>
          )}
          {ratio.benchmark && (
            <p className={`text-slate-500 ${expandedView ? 'text-[11px]' : 'text-[9px]'}`}>
              <span className="text-slate-400 font-semibold">Benchmark: </span>{ratio.benchmark}
            </p>
          )}
          {ratio.description && (
            <p className={`text-slate-400 leading-relaxed ${expandedView ? 'text-xs' : 'text-[9px]'}`}>{ratio.description}</p>
          )}
          {ratio.anomaly && (
            <p className={`text-amber-400 font-semibold ${expandedView ? 'text-xs' : 'text-[9px]'}`}>⚠ Anomaly detected — review recommended</p>
          )}

          {/* Drill-down: source numbers (averaged) */}
          {ratio.components && ratio.components.length > 0 && (
            <DerivationTable
              components={ratio.components}
              unit={ratio.unit}
              value={ratio.value}
              expandedView={expandedView}
            />
          )}

          {/* Period-by-period breakdown */}
          {ratio.period_values && ratio.period_values.length > 0 && (
            <PeriodBreakdown
              periods={ratio.period_values}
              unit={ratio.unit}
              expandedView={expandedView}
            />
          )}
        </div>
      )}
    </div>
  )
}

function Section({ title, ratios, icon: Icon, expandedView = false }) {
  if (!ratios || ratios.length === 0) return null
  const highCount = ratios.filter(r => r.risk_level === 'HIGH').length
  const medCount  = ratios.filter(r => r.risk_level === 'MEDIUM').length

  return (
    <div className="mb-5">
      <div className="flex items-center gap-2 mb-2.5">
        <Icon className={`text-slate-500 flex-shrink-0 ${expandedView ? 'w-4 h-4' : 'w-3.5 h-3.5'}`} />
        <p className={`font-semibold text-slate-400 uppercase tracking-wider ${expandedView ? 'text-xs' : 'text-[11px]'}`}>{title}</p>
        <div className="flex gap-1 ml-auto">
          {highCount > 0 && (
            <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-red-500/15 border border-red-500/30 text-red-400 font-bold">
              {highCount} HIGH
            </span>
          )}
          {medCount > 0 && (
            <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-amber-500/15 border border-amber-500/30 text-amber-400 font-bold">
              {medCount} MED
            </span>
          )}
        </div>
      </div>
      {/* 2-column grid in expanded view, single column in sidebar */}
      <div className={expandedView ? 'grid grid-cols-2 gap-2' : 'space-y-1.5'}>
        {ratios.map(r => <RatioCard key={r.name} ratio={r} expanded={expandedView} />)}
      </div>
    </div>
  )
}

// ── Trend table ───────────────────────────────────────────────────────────────

// Per-ratio colour thresholds — must match backend _TREND_DEFS
const TREND_THRESHOLDS = {
  20: { low: 60, high: 80, invert: false },   // ITC to Taxable
  43: { low: 5,  high: 20, invert: true  },   // Cash Payment to Liability
  42: { low: 80, high: 90, invert: false },   // ITC Utilization
  13: { low: 5,  high: 15, invert: false },   // ITC Reversal Ratio
  30: { low: 5,  high: 15, invert: false },   // B2B Credit Note Ratio
  1:  { low: 10, high: 30, invert: false },   // Deemed Export Ratio
  41: { low: 30, high: 60, invert: false },   // Export Turnover Ratio
  11: { low: 15, high: 30, invert: false },   // ISD Credit Ratio
}

function cellColor(val, direction, slNo) {
  if (val === null || val === undefined) return 'text-slate-600'
  const t = TREND_THRESHOLDS[slNo]
  if (!t) return 'text-slate-300'
  if (t.invert) {
    if (val < t.low)  return 'text-red-400'
    if (val < t.high) return 'text-amber-400'
    return 'text-emerald-400'
  } else {
    if (val > t.high) return 'text-red-400'
    if (val > t.low)  return 'text-amber-400'
    return 'text-emerald-400'
  }
}

function TrendIcon({ trend, direction }) {
  const risky = (direction === 'high_bad' && trend === 'rising') ||
                (direction === 'low_bad'  && trend === 'falling')
  const safe  = (direction === 'high_bad' && trend === 'falling') ||
                (direction === 'low_bad'  && trend === 'rising')

  if (trend === 'stable') return <Minus className="w-3 h-3 text-slate-500" />
  if (trend === 'rising')
    return <TrendingUp  className={`w-3 h-3 ${risky ? 'text-red-400' : safe ? 'text-emerald-400' : 'text-slate-400'}`} />
  return   <TrendingDown className={`w-3 h-3 ${risky ? 'text-red-400' : safe ? 'text-emerald-400' : 'text-slate-400'}`} />
}

// ── Trend cell drill-down popup ───────────────────────────────────────────────

function TrendCellPopup({ ratio, fy, val, onClose }) {
  const comps = ratio.components?.[fy] || []
  const [num, den] = comps

  return (
    <div className="fixed inset-0 z-[200] flex items-center justify-center" onClick={onClose}>
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" />
      <div
        className="relative z-10 bg-slate-900 border border-slate-700 rounded-xl shadow-2xl p-4 w-[340px] max-w-[90vw]"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start justify-between gap-2 mb-3">
          <div>
            <p className="text-xs font-semibold text-white">{ratio.name}</p>
            <p className="text-[10px] text-slate-500">{fy}</p>
          </div>
          <div className="flex items-center gap-2">
            <span className={`text-lg font-bold font-mono ${cellColor(val, ratio.direction, ratio.sl_no)}`}>
              {val !== undefined && val !== null ? `${val}${ratio.unit}` : '—'}
            </span>
            <button onClick={onClose} className="text-slate-600 hover:text-slate-300 text-xs px-1">✕</button>
          </div>
        </div>

        {/* Source numbers */}
        {comps.length > 0 && (
          <>
            <p className="text-[9px] text-slate-500 font-semibold uppercase tracking-wider mb-1.5">Source Numbers</p>
            <div className="rounded-lg overflow-hidden border border-slate-700/50">
              <table className="w-full border-collapse">
                <thead>
                  <tr className="bg-slate-800/60">
                    <th className="text-left px-2 py-1.5 text-[9px] text-slate-500 font-medium">Input</th>
                    <th className="text-left px-2 py-1.5 text-[9px] text-slate-500 font-medium">Table</th>
                    <th className="text-right px-2 py-1.5 text-[9px] text-slate-500 font-medium">Value</th>
                  </tr>
                </thead>
                <tbody>
                  {comps.map((c, i) => (
                    <tr key={i} className="border-t border-slate-700/30">
                      <td className="px-2 py-1.5 text-[10px] text-slate-300 font-medium">{c.label}</td>
                      <td className="px-2 py-1.5 text-[9px] text-slate-500 font-mono">{c.table}</td>
                      <td className="px-2 py-1.5 text-right text-[10px] font-mono font-bold text-slate-200">
                        {c.value !== null && c.value !== undefined ? fmtINR(c.value) : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {/* Computation line */}
            {num && den && val !== null && val !== undefined && (
              <p className="mt-2 text-[9px] text-slate-600 font-mono">
                = {fmtINR(num.value)} ÷ {fmtINR(den.value)} × 100
                <span className="ml-1 font-bold text-slate-300">= {val}{ratio.unit}</span>
              </p>
            )}
          </>
        )}
      </div>
    </div>
  )
}

function TrendTable({ trend, expandedView = false }) {
  const { fys, ratios } = trend
  const [popup, setPopup] = useState(null)   // { ratio, fy, val }

  if (!fys || fys.length === 0) return (
    <div className="py-8 text-center text-xs text-slate-600">
      Upload returns from multiple Financial Years to see trend analysis
    </div>
  )

  const textSm  = expandedView ? 'text-xs'    : 'text-[10px]'
  const textXs  = expandedView ? 'text-[11px]': 'text-[9px]'
  const padY    = expandedView ? 'py-3'       : 'py-2'
  const padX    = expandedView ? 'px-3'       : 'px-2'
  const minCol  = expandedView ? 'min-w-[200px]' : 'min-w-[130px]'
  const minFY   = expandedView ? 'min-w-[90px]'  : 'min-w-[64px]'

  return (
    <>
      {popup && (
        <TrendCellPopup
          ratio={popup.ratio}
          fy={popup.fy}
          val={popup.val}
          onClose={() => setPopup(null)}
        />
      )}

      <div className="overflow-x-auto -mx-1">
        <table className="w-full border-collapse" style={{ minWidth: expandedView ? 600 : 300 }}>
          <thead>
            <tr className="border-b border-slate-700">
              <th className={`text-left text-slate-500 font-semibold ${padY} pr-4 sticky left-0 bg-slate-900 ${minCol} z-10 ${textSm}`}>
                Ratio
              </th>
              {fys.map(fy => (
                <th key={fy} className={`text-center text-slate-400 font-semibold ${padY} ${padX} whitespace-nowrap ${minFY} ${textSm}`}>
                  {fy.replace('FY ', '')}
                </th>
              ))}
              <th className={`text-center text-slate-500 font-semibold ${padY} ${padX} ${textSm}`}>Trend</th>
            </tr>
          </thead>
          <tbody>
            {ratios.map(r => (
              <tr key={r.sl_no} className="border-t border-slate-800/40 hover:bg-slate-800/20 transition-colors">
                <td className={`${padY} pr-4 sticky left-0 bg-slate-900 z-10 font-medium leading-tight ${textSm} ${r.trend_risky ? 'text-amber-300' : 'text-slate-300'}`}>
                  {r.trend_risky && <AlertTriangle className="w-3 h-3 inline mr-1 text-amber-400 flex-shrink-0" />}
                  {r.name}
                </td>
                {fys.map(fy => {
                  const val = r.values[fy]
                  const hasData = val !== undefined && val !== null
                  return (
                    <td
                      key={fy}
                      onClick={() => hasData && setPopup({ ratio: r, fy, val })}
                      className={`text-center ${padY} ${padX} font-mono font-bold
                        ${cellColor(val, r.direction, r.sl_no)}
                        ${expandedView ? 'text-sm' : 'text-[10px]'}
                        ${hasData ? 'cursor-pointer hover:underline hover:opacity-80 transition-opacity' : ''}`}
                      title={hasData ? 'Click to see source numbers' : undefined}
                    >
                      {hasData ? `${val}${r.unit}` : '—'}
                    </td>
                  )
                })}
                <td className={`text-center ${padY} ${padX}`}>
                  <div className="flex items-center justify-center gap-1">
                    <TrendIcon trend={r.trend} direction={r.direction} />
                    {expandedView && (
                      <span className={`${textXs} ${r.trend_risky ? 'text-red-400' : r.trend === 'stable' ? 'text-slate-600' : 'text-emerald-400'} capitalize`}>
                        {r.trend}
                      </span>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        <div className={`flex items-center gap-3 mt-3 px-1 flex-wrap ${textXs}`}>
          <span className="text-slate-600 font-semibold uppercase tracking-wider">Legend:</span>
          <span className="text-emerald-400">● Low risk</span>
          <span className="text-amber-400">● Medium</span>
          <span className="text-red-400">● High risk</span>
          <span className="text-amber-300 ml-1">⚠ Risky trend direction</span>
        </div>
        <p className={`text-slate-700 mt-1.5 px-1 ${textXs}`}>
          Click any value to see source numbers · FY totals = Apr–Mar sum of all uploaded months
        </p>
      </div>
    </>
  )
}

// ── Main panel ────────────────────────────────────────────────────────────────

export default function RiskRatiosPanel({ uploadedFiles = [], expanded: expandedView = false }) {
  const [data, setData]       = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState(null)
  const [activeTab, setActiveTab] = useState('ratios')   // 'ratios' | 'trend'

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const { data: res } = await getRiskRatios()
      setData(res)
    } catch (e) {
      setError('Failed to load risk ratios')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (uploadedFiles.length > 0) load()
  }, [uploadedFiles.length])

  if (loading) return (
    <div className="flex items-center gap-2 py-6 justify-center text-slate-600 text-xs">
      <RefreshCw className="w-4 h-4 animate-spin" /> Computing risk ratios…
    </div>
  )

  if (error) return (
    <div className="py-6 text-center text-xs text-red-400">
      {error}
      <button onClick={load} className="ml-2 underline">retry</button>
    </div>
  )

  if (!data || !data.available) return (
    <div className="flex flex-col items-center py-8 text-slate-700 text-xs gap-2">
      <ShieldAlert className="w-8 h-8 opacity-30" />
      Upload GSTR files to compute risk ratios
    </div>
  )

  const allRatios = [
    ...(data.gstr1       || []),
    ...(data.gstr3b      || []),
    ...(data.cross       || []),
    ...(data.multiperiod || []),
  ]
  const highCount  = allRatios.filter(r => r.risk_level === 'HIGH').length
  const medCount   = allRatios.filter(r => r.risk_level === 'MEDIUM').length
  const totalCount = allRatios.filter(r => r.available).length

  const fyCount    = data.trend?.fys?.length || 0
  const trendRisky = data.trend?.ratios?.filter(r => r.trend_risky).length || 0

  return (
    <div>
      {/* Summary strip */}
      <div className="flex items-center gap-2 mb-3 px-2 py-1.5 rounded-lg bg-slate-900/60 border border-slate-800">
        {highCount > 0
          ? <ShieldAlert className="w-3.5 h-3.5 text-red-400 flex-shrink-0" />
          : <ShieldCheck className="w-3.5 h-3.5 text-emerald-400 flex-shrink-0" />}
        <p className="text-[10px] text-slate-400">
          <span className="font-semibold text-white">{totalCount}</span> ratios ·{' '}
          {highCount > 0 && <span className="text-red-400 font-semibold">{highCount} HIGH</span>}
          {highCount > 0 && medCount > 0 && ' · '}
          {medCount  > 0 && <span className="text-amber-400 font-semibold">{medCount} MED</span>}
          {highCount === 0 && medCount === 0 && <span className="text-emerald-400 font-semibold">All LOW</span>}
          {fyCount > 0 && <span className="text-slate-500"> · {fyCount} FY trend</span>}
        </p>
        <button onClick={load} className="ml-auto text-slate-600 hover:text-slate-400 transition-colors" title="Refresh">
          <RefreshCw className="w-3 h-3" />
        </button>
      </div>

      {/* Tab switcher */}
      <div className="flex gap-1 mb-3 bg-slate-900 border border-slate-800 rounded-lg p-0.5">
        <button
          onClick={() => setActiveTab('ratios')}
          className={`flex-1 py-1 text-[10px] font-semibold rounded-md transition-all ${
            activeTab === 'ratios'
              ? 'bg-slate-700 text-white'
              : 'text-slate-500 hover:text-slate-300'
          }`}
        >
          Ratios
        </button>
        <button
          onClick={() => setActiveTab('trend')}
          className={`flex-1 py-1 text-[10px] font-semibold rounded-md transition-all ${
            activeTab === 'trend'
              ? 'bg-slate-700 text-white'
              : 'text-slate-500 hover:text-slate-300'
          }`}
        >
          Trend {fyCount > 0 && <span className="ml-0.5 opacity-70">({fyCount} FY{fyCount > 1 ? 's' : ''})</span>}
          {trendRisky > 0 && <span className="ml-1 text-amber-400">⚠{trendRisky}</span>}
        </button>
      </div>

      {/* Ratios tab */}
      {activeTab === 'ratios' && (
        <>
          <p className={`text-slate-600 mb-3 px-1 ${expandedView ? 'text-[11px]' : 'text-[9px]'}`}>
            Click any ratio to see formula, benchmark, interpretation, and the exact source numbers used
          </p>
          <Section title="GSTR-1 Supply Risk"           ratios={data.gstr1}       icon={ShieldAlert} expandedView={expandedView} />
          <Section title="GSTR-3B Liability & ITC"      ratios={data.gstr3b}      icon={ShieldAlert} expandedView={expandedView} />
          {data.has_cross && (
            <Section title="Cross-Form (GSTR-1 vs 3B)" ratios={data.cross}       icon={ShieldAlert} expandedView={expandedView} />
          )}
          {data.has_multiperiod && (
            <Section title="Multi-Period Trend"         ratios={data.multiperiod} icon={ShieldAlert} expandedView={expandedView} />
          )}
          {data.gstr2b && data.gstr2b.length > 0 && (
            <Section title="GSTR-2B (Pending Data)"    ratios={data.gstr2b}      icon={ShieldAlert} expandedView={expandedView} />
          )}
        </>
      )}

      {/* Trend tab */}
      {activeTab === 'trend' && (
        <>
          {fyCount >= 2 && trendRisky > 0 && (
            <div className="mb-3 px-2 py-1.5 rounded-lg bg-amber-500/10 border border-amber-500/30">
              <p className={`text-amber-400 font-semibold ${expandedView ? 'text-xs' : 'text-[10px]'}`}>
                ⚠ {trendRisky} ratio{trendRisky > 1 ? 's are' : ' is'} trending toward risk — review recommended
              </p>
            </div>
          )}
          <TrendTable trend={data.trend || { fys: [], ratios: [] }} expandedView={expandedView} />
        </>
      )}

      <p className="text-[9px] text-slate-700 text-center pt-2 mt-2 border-t border-slate-800/40">
        DGARM Risk Ratio Framework v2 · {data.total_ratios} official ratios
      </p>
    </div>
  )
}
