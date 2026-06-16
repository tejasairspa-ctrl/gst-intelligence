/**
 * MainDashboard — Primary center panel.
 *
 * Replaces the chat interface as the center panel in DashboardLayout.
 * Single function controls the view: showDashboard(mode).
 * mode = "kpi" → KPI cards + charts for active file
 * mode = "mom" → Month-over-Month table across all uploaded files
 *
 * LOCKED ARCHITECTURE — do not redesign.
 */
import React, { useEffect, useState } from 'react'
import { BarChart2, TrendingUp, Calendar, AlertCircle, FileSpreadsheet } from 'lucide-react'
import { useApp } from '../context/AppContext'
import { KPIGrid } from './KPICard'
import { TaxDistributionChart, ITCChart, SalesBreakdownChart } from './AnalyticsCharts'
import FileUpload from './FileUpload'
import { exportMOMExcel, exportMOM3BExcel, exportMOM9Excel } from '../api/client'
import GSTR2BCompiler from './GSTR2BCompiler'

// ── Number formatter (Raw / Lakhs / Crores) ──────────────────────────────────
function fmtVal(val, mode = 'raw') {
  if (val == null || val === undefined) return '—'
  const n = Number(val)
  if (isNaN(n)) return '—'
  if (mode === 'cr') return (n / 1e7).toFixed(2) + ' Cr'
  if (mode === 'l')  return (n / 1e5).toFixed(2) + ' L'
  return n.toLocaleString('en-IN', { maximumFractionDigits: 2 })
}

// ── KPI mode (single file) ────────────────────────────────────────────────────
function KPIDashboard({ analytics, activeFile }) {
  if (!analytics) {
    return (
      <div className="flex flex-col items-center justify-center h-64 text-slate-700">
        <BarChart2 className="w-12 h-12 mb-3 opacity-30" />
        <p className="text-sm">Select a file from the left panel to view analytics</p>
      </div>
    )
  }

  const kpis     = analytics.kpis     || []
  const charts   = analytics.charts   || {}
  const insights = analytics.insights || []

  const hasTaxChart   = charts.tax_distribution?.length > 0
  const hasSalesChart = charts.sales_breakdown?.length > 0
  const hasITCChart   = charts.itc_breakdown?.length > 0

  return (
    <div className="space-y-6">
      {/* KPIs */}
      <section>
        <h2 className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider mb-3">
          Key Performance Indicators
          {activeFile?.gst_type && (
            <span className="ml-2 text-slate-600 normal-case font-normal">
              — {activeFile.gst_type}{activeFile.period ? ` · ${activeFile.period}` : ''}
            </span>
          )}
        </h2>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
          {kpis.map((k) => (
            <div key={k.label} className="kpi-card p-4">
              <p className="text-[11px] text-slate-500 font-medium leading-tight">{k.label}</p>
              {k.available && k.value != null ? (
                <p className="text-xl font-bold text-white mt-1 font-mono leading-none">
                  {k.unit === '₹'
                    ? `₹${Number(k.value).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
                    : k.unit === '%'
                    ? `${Number(k.value).toFixed(2)}%`
                    : `${Number(k.value).toFixed(2)}${k.unit || ''}`}
                </p>
              ) : (
                <p className="text-xs text-slate-700 italic mt-1">Not in document</p>
              )}
            </div>
          ))}
        </div>
      </section>

      {/* Charts */}
      {(hasTaxChart || hasSalesChart || hasITCChart) && (
        <section>
          <h2 className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider mb-3">
            Charts
          </h2>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {hasTaxChart   && <TaxDistributionChart data={charts.tax_distribution} />}
            {hasSalesChart && <SalesBreakdownChart  data={charts.sales_breakdown}  />}
          </div>
          {hasITCChart && (
            <div className="mt-4">
              <ITCChart data={charts.itc_breakdown} />
            </div>
          )}
        </section>
      )}

      {/* Insights */}
      {insights.length > 0 && (
        <section>
          <h2 className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider mb-3">
            Insights
          </h2>
          <div className="space-y-2">
            {insights.map((ins, i) => (
              <div key={i} className="flex gap-2.5 p-3 rounded-lg bg-blue-600/5 border border-blue-600/15">
                <span className="flex-shrink-0 w-5 h-5 rounded-full bg-blue-600/20 text-blue-400 text-[10px] font-bold flex items-center justify-center">
                  {i + 1}
                </span>
                <p className="text-xs text-slate-400 leading-relaxed">{ins}</p>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  )
}

// ── Anomaly helpers ────────────────────────────────────────────────────────────
const ANOM_THRESHOLD = 0.5
const _isAnom = (cur, prev) => {
  if (cur === null || cur === undefined) return false
  if (prev === null || prev === undefined) return false
  if (Math.abs(Number(prev)) < 1) return false
  return Math.abs((Number(cur) - Number(prev)) / Math.abs(Number(prev))) >= ANOM_THRESHOLD
}

// ── GSTR-1 MOM table ──────────────────────────────────────────────────────────
function GSTR1Table({ files, analyticsById, fmtMode, annualFileId, annualFile, annualExt }) {
  const filesWithData = files.filter((f) => analyticsById[f.id])
  if (filesWithData.length === 0) return null

  const buildRow = (f, ext) => ({
    period:       f.period   || '—',
    // 4A B2B Regular
    b2b_taxable:  ext.b2b_taxable_value  ?? null,
    b2b_igst:     ext.b2b_igst           ?? null,
    b2b_cgst:     ext.b2b_cgst           ?? null,
    b2b_sgst:     ext.b2b_sgst           ?? null,
    // 4B B2B RCM
    b2b_rcm_taxable: ext.b2b_rcm_taxable ?? null,
    b2b_rcm_igst:    ext.b2b_rcm_igst    ?? null,
    b2b_rcm_cgst:    ext.b2b_rcm_cgst    ?? null,
    b2b_rcm_sgst:    ext.b2b_rcm_sgst    ?? null,
    // 5A/5B B2CL
    b2cl_taxable: ext.b2cl_taxable_value ?? null,
    b2cl_igst:    ext.b2cl_igst          ?? null,
    // 7 B2CS
    b2cs_taxable: ext.b2cs_taxable_value ?? null,
    b2cs_igst:    ext.b2cs_igst          ?? null,
    b2cs_cgst:    ext.b2cs_cgst          ?? null,
    b2cs_sgst:    ext.b2cs_sgst          ?? null,
    // 8 NIL / Exempt
    nil_rated:    ext.nil_taxable_value  ?? null,
    exempt:       ext.nil_exempt         ?? null,
    non_gst:      ext.nil_non_gst        ?? null,
    // 6A Exports
    exp_expwp_taxable:  ext.exp_expwp_taxable  ?? null,
    exp_expwp_igst:     ext.exp_expwp_igst     ?? null,
    exp_expwop_taxable: ext.exp_expwop_taxable ?? null,
    // 6B SEZ
    sez_sezwp_taxable:  ext.sez_sezwp_taxable  ?? null,
    sez_sezwp_igst:     ext.sez_sezwp_igst     ?? null,
    sez_sezwop_taxable: ext.sez_sezwop_taxable ?? null,
    // 6C Deemed Exports
    de_taxable: ext.de_taxable ?? null,
    de_igst:    ext.de_igst    ?? null,
    de_cgst:    ext.de_cgst    ?? null,
    de_sgst:    ext.de_sgst    ?? null,
    // 9B CDN Registered
    cdnr_taxable: ext.cdnr_taxable ?? ext.cdn_value ?? null,
    cdnr_igst:    ext.cdnr_igst    ?? ext.cdn_igst  ?? null,
    cdnr_cgst:    ext.cdnr_cgst    ?? ext.cdn_cgst  ?? null,
    cdnr_sgst:    ext.cdnr_sgst    ?? ext.cdn_sgst  ?? null,
    // 9B CDN Unregistered
    cdnur_taxable: ext.cdnur_taxable ?? null,
    cdnur_igst:    ext.cdnur_igst    ?? null,
    cdnur_cgst:    ext.cdnur_cgst    ?? null,
    cdnur_sgst:    ext.cdnur_sgst    ?? null,
    // 9C CDNRA / CDNURA
    cdnra_taxable:  ext.cdnra_taxable  ?? null,
    cdnra_igst:     ext.cdnra_igst     ?? null,
    cdnra_cgst:     ext.cdnra_cgst     ?? null,
    cdnra_sgst:     ext.cdnra_sgst     ?? null,
    cdnura_taxable: ext.cdnura_taxable ?? null,
    cdnura_igst:    ext.cdnura_igst    ?? null,
    // 9A Amendments
    amend_b2b_taxable:  ext.amend_b2b_taxable  ?? null,
    amend_b2b_igst:     ext.amend_b2b_igst     ?? null,
    amend_b2b_cgst:     ext.amend_b2b_cgst     ?? null,
    amend_b2b_sgst:     ext.amend_b2b_sgst     ?? null,
    amend_b2cl_taxable: ext.amend_b2cl_taxable ?? null,
    amend_b2cl_igst:    ext.amend_b2cl_igst    ?? null,
    amend_exp_taxable:  ext.amend_exp_taxable  ?? null,
    amend_exp_igst:     ext.amend_exp_igst     ?? null,
    amend_sez_taxable:  ext.amend_sez_taxable  ?? null,
    amend_sez_igst:     ext.amend_sez_igst     ?? null,
    amend_de_taxable:   ext.amend_de_taxable   ?? null,
    amend_de_igst:      ext.amend_de_igst      ?? null,
    // 10 B2CS Amendments
    amend_b2cs_taxable: ext.amend_b2cs_taxable ?? null,
    amend_b2cs_igst:    ext.amend_b2cs_igst    ?? null,
    amend_b2cs_cgst:    ext.amend_b2cs_cgst    ?? null,
    amend_b2cs_sgst:    ext.amend_b2cs_sgst    ?? null,
    // 11A/11B Advances
    adv_recv_taxable: ext.adv_recv_taxable ?? null,
    adv_recv_igst:    ext.adv_recv_igst    ?? null,
    adv_recv_cgst:    ext.adv_recv_cgst    ?? null,
    adv_recv_sgst:    ext.adv_recv_sgst    ?? null,
    adv_adj_taxable:  ext.adv_adj_taxable  ?? null,
    adv_adj_igst:     ext.adv_adj_igst     ?? null,
    adv_adj_cgst:     ext.adv_adj_cgst     ?? null,
    adv_adj_sgst:     ext.adv_adj_sgst     ?? null,
    // 14 E-Commerce / 15 u/s 9(5)
    eco_taxable: ext.eco_taxable ?? null,
    eco_igst:    ext.eco_igst    ?? null,
    eco_cgst:    ext.eco_cgst    ?? null,
    eco_sgst:    ext.eco_sgst    ?? null,
    s95_taxable: ext.s95_taxable ?? null,
    s95_igst:    ext.s95_igst    ?? null,
    s95_cgst:    ext.s95_cgst    ?? null,
    s95_sgst:    ext.s95_sgst    ?? null,
    // 12 HSN Summary / Total Tax
    hsn_taxable:  ext.total_taxable_value ?? null,
    hsn_igst:     ext.total_igst          ?? null,
    hsn_cgst:     ext.total_cgst          ?? null,
    hsn_sgst:     ext.total_sgst          ?? null,
  })

  const rows = filesWithData.map((f) => buildRow(f, analyticsById[f.id]?.extracted_data || {}))
  const sum  = (key) => rows.reduce((s, r) => s + (r[key] ?? 0), 0) || null

  const annualRow = (annualFile && annualExt) ? buildRow(annualFile, annualExt) : null

  const diffVal = (key) => {
    if (!annualRow) return null
    const d = (annualRow[key] ?? 0) - (sum(key) ?? 0)
    return Math.abs(d) < 0.01 ? 'NIL' : d
  }
  const fmtDiff = (v) => {
    if (v === null || v === undefined) return '—'
    if (v === 'NIL') return 'Nil'
    return fmtVal(v, fmtMode)
  }
  const diffCls = (v) => {
    const base = 'px-3 py-2 text-right font-mono whitespace-nowrap text-[10px]'
    if (v === null || v === 'NIL') return `${base} text-emerald-600`
    return v > 0 ? `${base} text-amber-400 font-semibold` : `${base} text-red-400 font-semibold`
  }

  // Anomaly class
  const anomCls = (rowIdx, key, base) => {
    if (rowIdx === 0) return base
    return _isAnom(rows[rowIdx][key], rows[rowIdx - 1][key])
      ? `${base} bg-amber-500/10 ring-1 ring-inset ring-amber-500/35`
      : base
  }

  const thG  = 'px-3 py-2 text-center text-[10px] font-bold text-slate-300 uppercase tracking-wider border-b border-slate-700'
  const thS  = 'px-3 py-2 text-right text-[10px] font-semibold text-slate-500 whitespace-nowrap'
  const tdM  = 'px-3 py-2.5 text-right font-mono text-slate-300 whitespace-nowrap'
  const tdB  = 'px-3 py-2.5 text-right font-mono text-slate-300 whitespace-nowrap border-l border-slate-800/60'
  const ftM  = 'px-3 py-2.5 text-right font-mono font-bold text-white whitespace-nowrap'
  const ftB  = 'px-3 py-2.5 text-right font-mono font-bold text-white whitespace-nowrap border-l border-slate-800/60'

  return (
    <div className="overflow-x-auto rounded-xl border border-slate-800">
      <table className="w-full text-xs border-collapse">
        <thead>
          <tr className="bg-slate-900/80 border-b border-slate-700">
            <th rowSpan={2} className="px-3 py-2 text-left text-[10px] font-bold text-slate-400 uppercase tracking-wider whitespace-nowrap align-bottom border-b border-slate-700">Period</th>
            <th colSpan={4} className={`${thG} border-l border-slate-700`}>4A - B2B Regular</th>
            <th colSpan={4} className={`${thG} border-l border-slate-700`}>4B - B2B RCM</th>
            <th colSpan={2} className={`${thG} border-l border-slate-700`}>5A/5B - B2CL</th>
            <th colSpan={4} className={`${thG} border-l border-slate-700`}>7 - B2CS</th>
            <th colSpan={3} className={`${thG} border-l border-slate-700`}>8 - NIL / Exempt</th>
            <th colSpan={2} className={`${thG} border-l border-slate-700`}>6A - EXPWP</th>
            <th colSpan={1} className={`${thG} border-l border-slate-700`}>6A - EXPWOP</th>
            <th colSpan={2} className={`${thG} border-l border-slate-700`}>6B - SEZWP</th>
            <th colSpan={1} className={`${thG} border-l border-slate-700`}>6B - SEZWOP</th>
            <th colSpan={4} className={`${thG} border-l border-slate-700`}>6C - Deemed Exports</th>
            <th colSpan={4} className={`${thG} border-l border-slate-700`}>9B - CDN Reg.</th>
            <th colSpan={4} className={`${thG} border-l border-slate-700`}>9B - CDN Unreg.</th>
            <th colSpan={4} className={`${thG} border-l border-slate-700`}>9C - CDNRA</th>
            <th colSpan={2} className={`${thG} border-l border-slate-700`}>9C - CDNURA</th>
            <th colSpan={4} className={`${thG} border-l border-slate-700`}>9A - Amend B2B</th>
            <th colSpan={2} className={`${thG} border-l border-slate-700`}>9A - Amend B2CL</th>
            <th colSpan={2} className={`${thG} border-l border-slate-700`}>9A - Amend Exp</th>
            <th colSpan={2} className={`${thG} border-l border-slate-700`}>9A - Amend SEZ</th>
            <th colSpan={2} className={`${thG} border-l border-slate-700`}>9A - Amend DE</th>
            <th colSpan={4} className={`${thG} border-l border-slate-700`}>10 - B2CS Amend</th>
            <th colSpan={4} className={`${thG} border-l border-slate-700`}>11A - Adv Received</th>
            <th colSpan={4} className={`${thG} border-l border-slate-700`}>11B - Adv Adjusted</th>
            <th colSpan={4} className={`${thG} border-l border-slate-700`}>14 - E-Commerce</th>
            <th colSpan={4} className={`${thG} border-l border-slate-700`}>15 - u/s 9(5)</th>
            <th colSpan={4} className={`${thG} border-l border-slate-700`}>12 - HSN Summary</th>
            <th colSpan={4} className={`${thG} border-l border-slate-700 text-blue-400`}>Total Tax</th>
          </tr>
          <tr className="bg-slate-900/60 border-b border-slate-800">
            {/* 4A B2B */}
            <th className={`${thS} border-l border-slate-700`}>Taxable</th><th className={thS}>IGST</th><th className={thS}>CGST</th><th className={thS}>SGST</th>
            {/* 4B RCM */}
            <th className={`${thS} border-l border-slate-700`}>Taxable</th><th className={thS}>IGST</th><th className={thS}>CGST</th><th className={thS}>SGST</th>
            {/* B2CL */}
            <th className={`${thS} border-l border-slate-700`}>Taxable</th><th className={thS}>IGST</th>
            {/* B2CS */}
            <th className={`${thS} border-l border-slate-700`}>Taxable</th><th className={thS}>IGST</th><th className={thS}>CGST</th><th className={thS}>SGST</th>
            {/* NIL */}
            <th className={`${thS} border-l border-slate-700`}>NIL</th><th className={thS}>Exempt</th><th className={thS}>Non-GST</th>
            {/* 6A EXPWP */}
            <th className={`${thS} border-l border-slate-700`}>Taxable</th><th className={thS}>IGST</th>
            {/* 6A EXPWOP */}
            <th className={`${thS} border-l border-slate-700`}>Taxable</th>
            {/* 6B SEZWP */}
            <th className={`${thS} border-l border-slate-700`}>Taxable</th><th className={thS}>IGST</th>
            {/* 6B SEZWOP */}
            <th className={`${thS} border-l border-slate-700`}>Taxable</th>
            {/* 6C DE */}
            <th className={`${thS} border-l border-slate-700`}>Taxable</th><th className={thS}>IGST</th><th className={thS}>CGST</th><th className={thS}>SGST</th>
            {/* CDNR */}
            <th className={`${thS} border-l border-slate-700`}>Taxable</th><th className={thS}>IGST</th><th className={thS}>CGST</th><th className={thS}>SGST</th>
            {/* CDNUR */}
            <th className={`${thS} border-l border-slate-700`}>Taxable</th><th className={thS}>IGST</th><th className={thS}>CGST</th><th className={thS}>SGST</th>
            {/* CDNRA */}
            <th className={`${thS} border-l border-slate-700`}>Taxable</th><th className={thS}>IGST</th><th className={thS}>CGST</th><th className={thS}>SGST</th>
            {/* CDNURA */}
            <th className={`${thS} border-l border-slate-700`}>Taxable</th><th className={thS}>IGST</th>
            {/* 9A Amend B2B */}
            <th className={`${thS} border-l border-slate-700`}>Taxable</th><th className={thS}>IGST</th><th className={thS}>CGST</th><th className={thS}>SGST</th>
            {/* 9A Amend B2CL */}
            <th className={`${thS} border-l border-slate-700`}>Taxable</th><th className={thS}>IGST</th>
            {/* 9A Amend Exp */}
            <th className={`${thS} border-l border-slate-700`}>Taxable</th><th className={thS}>IGST</th>
            {/* 9A Amend SEZ */}
            <th className={`${thS} border-l border-slate-700`}>Taxable</th><th className={thS}>IGST</th>
            {/* 9A Amend DE */}
            <th className={`${thS} border-l border-slate-700`}>Taxable</th><th className={thS}>IGST</th>
            {/* 10 B2CS Amend */}
            <th className={`${thS} border-l border-slate-700`}>Taxable</th><th className={thS}>IGST</th><th className={thS}>CGST</th><th className={thS}>SGST</th>
            {/* 11A Advances */}
            <th className={`${thS} border-l border-slate-700`}>Taxable</th><th className={thS}>IGST</th><th className={thS}>CGST</th><th className={thS}>SGST</th>
            {/* 11B Adjusted */}
            <th className={`${thS} border-l border-slate-700`}>Taxable</th><th className={thS}>IGST</th><th className={thS}>CGST</th><th className={thS}>SGST</th>
            {/* 14 ECO */}
            <th className={`${thS} border-l border-slate-700`}>Taxable</th><th className={thS}>IGST</th><th className={thS}>CGST</th><th className={thS}>SGST</th>
            {/* 15 9(5) */}
            <th className={`${thS} border-l border-slate-700`}>Taxable</th><th className={thS}>IGST</th><th className={thS}>CGST</th><th className={thS}>SGST</th>
            {/* HSN */}
            <th className={`${thS} border-l border-slate-700`}>Taxable</th><th className={thS}>IGST</th><th className={thS}>CGST</th><th className={thS}>SGST</th>
            {/* Total */}
            <th className={`${thS} border-l border-slate-700 text-blue-300`}>Taxable</th><th className={`${thS} text-blue-300`}>IGST</th><th className={`${thS} text-blue-300`}>CGST</th><th className={`${thS} text-blue-300`}>SGST</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-b border-slate-800/50 hover:bg-slate-800/20 transition-colors">
              <td className="px-3 py-2.5 text-slate-300 font-medium whitespace-nowrap">{r.period}</td>
              {/* 4A B2B */}
              <td className={anomCls(i,'b2b_taxable',     tdB)}>{fmtVal(r.b2b_taxable,      fmtMode)}</td>
              <td className={anomCls(i,'b2b_igst',        tdM)}>{fmtVal(r.b2b_igst,         fmtMode)}</td>
              <td className={anomCls(i,'b2b_cgst',        tdM)}>{fmtVal(r.b2b_cgst,         fmtMode)}</td>
              <td className={anomCls(i,'b2b_sgst',        tdM)}>{fmtVal(r.b2b_sgst,         fmtMode)}</td>
              {/* 4B RCM */}
              <td className={anomCls(i,'b2b_rcm_taxable', tdB)}>{fmtVal(r.b2b_rcm_taxable,  fmtMode)}</td>
              <td className={anomCls(i,'b2b_rcm_igst',    tdM)}>{fmtVal(r.b2b_rcm_igst,     fmtMode)}</td>
              <td className={anomCls(i,'b2b_rcm_cgst',    tdM)}>{fmtVal(r.b2b_rcm_cgst,     fmtMode)}</td>
              <td className={anomCls(i,'b2b_rcm_sgst',    tdM)}>{fmtVal(r.b2b_rcm_sgst,     fmtMode)}</td>
              {/* B2CL */}
              <td className={anomCls(i,'b2cl_taxable',    tdB)}>{fmtVal(r.b2cl_taxable,      fmtMode)}</td>
              <td className={anomCls(i,'b2cl_igst',       tdM)}>{fmtVal(r.b2cl_igst,         fmtMode)}</td>
              {/* B2CS */}
              <td className={anomCls(i,'b2cs_taxable',    tdB)}>{fmtVal(r.b2cs_taxable,      fmtMode)}</td>
              <td className={anomCls(i,'b2cs_igst',       tdM)}>{fmtVal(r.b2cs_igst,         fmtMode)}</td>
              <td className={anomCls(i,'b2cs_cgst',       tdM)}>{fmtVal(r.b2cs_cgst,         fmtMode)}</td>
              <td className={anomCls(i,'b2cs_sgst',       tdM)}>{fmtVal(r.b2cs_sgst,         fmtMode)}</td>
              {/* NIL */}
              <td className={anomCls(i,'nil_rated',       tdB)}>{fmtVal(r.nil_rated,          fmtMode)}</td>
              <td className={anomCls(i,'exempt',          tdM)}>{fmtVal(r.exempt,             fmtMode)}</td>
              <td className={anomCls(i,'non_gst',         tdM)}>{fmtVal(r.non_gst,            fmtMode)}</td>
              {/* 6A EXPWP / EXPWOP */}
              <td className={anomCls(i,'exp_expwp_taxable', tdB)}>{fmtVal(r.exp_expwp_taxable,  fmtMode)}</td>
              <td className={anomCls(i,'exp_expwp_igst',    tdM)}>{fmtVal(r.exp_expwp_igst,     fmtMode)}</td>
              <td className={anomCls(i,'exp_expwop_taxable',tdB)}>{fmtVal(r.exp_expwop_taxable, fmtMode)}</td>
              {/* 6B SEZWP / SEZWOP */}
              <td className={anomCls(i,'sez_sezwp_taxable', tdB)}>{fmtVal(r.sez_sezwp_taxable,  fmtMode)}</td>
              <td className={anomCls(i,'sez_sezwp_igst',    tdM)}>{fmtVal(r.sez_sezwp_igst,     fmtMode)}</td>
              <td className={anomCls(i,'sez_sezwop_taxable',tdB)}>{fmtVal(r.sez_sezwop_taxable, fmtMode)}</td>
              {/* 6C DE */}
              <td className={anomCls(i,'de_taxable',       tdB)}>{fmtVal(r.de_taxable,          fmtMode)}</td>
              <td className={anomCls(i,'de_igst',          tdM)}>{fmtVal(r.de_igst,             fmtMode)}</td>
              <td className={anomCls(i,'de_cgst',          tdM)}>{fmtVal(r.de_cgst,             fmtMode)}</td>
              <td className={anomCls(i,'de_sgst',          tdM)}>{fmtVal(r.de_sgst,             fmtMode)}</td>
              {/* CDNR */}
              <td className={anomCls(i,'cdnr_taxable',     tdB)}>{fmtVal(r.cdnr_taxable,        fmtMode)}</td>
              <td className={anomCls(i,'cdnr_igst',        tdM)}>{fmtVal(r.cdnr_igst,           fmtMode)}</td>
              <td className={anomCls(i,'cdnr_cgst',        tdM)}>{fmtVal(r.cdnr_cgst,           fmtMode)}</td>
              <td className={anomCls(i,'cdnr_sgst',        tdM)}>{fmtVal(r.cdnr_sgst,           fmtMode)}</td>
              {/* CDNUR */}
              <td className={anomCls(i,'cdnur_taxable',    tdB)}>{fmtVal(r.cdnur_taxable,       fmtMode)}</td>
              <td className={anomCls(i,'cdnur_igst',       tdM)}>{fmtVal(r.cdnur_igst,          fmtMode)}</td>
              <td className={anomCls(i,'cdnur_cgst',       tdM)}>{fmtVal(r.cdnur_cgst,          fmtMode)}</td>
              <td className={anomCls(i,'cdnur_sgst',       tdM)}>{fmtVal(r.cdnur_sgst,          fmtMode)}</td>
              {/* CDNRA */}
              <td className={anomCls(i,'cdnra_taxable',    tdB)}>{fmtVal(r.cdnra_taxable,       fmtMode)}</td>
              <td className={anomCls(i,'cdnra_igst',       tdM)}>{fmtVal(r.cdnra_igst,          fmtMode)}</td>
              <td className={anomCls(i,'cdnra_cgst',       tdM)}>{fmtVal(r.cdnra_cgst,          fmtMode)}</td>
              <td className={anomCls(i,'cdnra_sgst',       tdM)}>{fmtVal(r.cdnra_sgst,          fmtMode)}</td>
              {/* CDNURA */}
              <td className={anomCls(i,'cdnura_taxable',   tdB)}>{fmtVal(r.cdnura_taxable,      fmtMode)}</td>
              <td className={anomCls(i,'cdnura_igst',      tdM)}>{fmtVal(r.cdnura_igst,         fmtMode)}</td>
              {/* 9A Amendments */}
              <td className={anomCls(i,'amend_b2b_taxable', tdB)}>{fmtVal(r.amend_b2b_taxable,  fmtMode)}</td>
              <td className={anomCls(i,'amend_b2b_igst',    tdM)}>{fmtVal(r.amend_b2b_igst,     fmtMode)}</td>
              <td className={anomCls(i,'amend_b2b_cgst',    tdM)}>{fmtVal(r.amend_b2b_cgst,     fmtMode)}</td>
              <td className={anomCls(i,'amend_b2b_sgst',    tdM)}>{fmtVal(r.amend_b2b_sgst,     fmtMode)}</td>
              <td className={anomCls(i,'amend_b2cl_taxable',tdB)}>{fmtVal(r.amend_b2cl_taxable, fmtMode)}</td>
              <td className={anomCls(i,'amend_b2cl_igst',   tdM)}>{fmtVal(r.amend_b2cl_igst,    fmtMode)}</td>
              <td className={anomCls(i,'amend_exp_taxable', tdB)}>{fmtVal(r.amend_exp_taxable,  fmtMode)}</td>
              <td className={anomCls(i,'amend_exp_igst',    tdM)}>{fmtVal(r.amend_exp_igst,     fmtMode)}</td>
              <td className={anomCls(i,'amend_sez_taxable', tdB)}>{fmtVal(r.amend_sez_taxable,  fmtMode)}</td>
              <td className={anomCls(i,'amend_sez_igst',    tdM)}>{fmtVal(r.amend_sez_igst,     fmtMode)}</td>
              <td className={anomCls(i,'amend_de_taxable',  tdB)}>{fmtVal(r.amend_de_taxable,   fmtMode)}</td>
              <td className={anomCls(i,'amend_de_igst',     tdM)}>{fmtVal(r.amend_de_igst,      fmtMode)}</td>
              {/* 10 B2CS Amend */}
              <td className={anomCls(i,'amend_b2cs_taxable',tdB)}>{fmtVal(r.amend_b2cs_taxable, fmtMode)}</td>
              <td className={anomCls(i,'amend_b2cs_igst',   tdM)}>{fmtVal(r.amend_b2cs_igst,    fmtMode)}</td>
              <td className={anomCls(i,'amend_b2cs_cgst',   tdM)}>{fmtVal(r.amend_b2cs_cgst,    fmtMode)}</td>
              <td className={anomCls(i,'amend_b2cs_sgst',   tdM)}>{fmtVal(r.amend_b2cs_sgst,    fmtMode)}</td>
              {/* 11A Advances */}
              <td className={anomCls(i,'adv_recv_taxable',  tdB)}>{fmtVal(r.adv_recv_taxable,   fmtMode)}</td>
              <td className={anomCls(i,'adv_recv_igst',     tdM)}>{fmtVal(r.adv_recv_igst,      fmtMode)}</td>
              <td className={anomCls(i,'adv_recv_cgst',     tdM)}>{fmtVal(r.adv_recv_cgst,      fmtMode)}</td>
              <td className={anomCls(i,'adv_recv_sgst',     tdM)}>{fmtVal(r.adv_recv_sgst,      fmtMode)}</td>
              {/* 11B Adjusted */}
              <td className={anomCls(i,'adv_adj_taxable',   tdB)}>{fmtVal(r.adv_adj_taxable,    fmtMode)}</td>
              <td className={anomCls(i,'adv_adj_igst',      tdM)}>{fmtVal(r.adv_adj_igst,       fmtMode)}</td>
              <td className={anomCls(i,'adv_adj_cgst',      tdM)}>{fmtVal(r.adv_adj_cgst,       fmtMode)}</td>
              <td className={anomCls(i,'adv_adj_sgst',      tdM)}>{fmtVal(r.adv_adj_sgst,       fmtMode)}</td>
              {/* 14 ECO */}
              <td className={anomCls(i,'eco_taxable',       tdB)}>{fmtVal(r.eco_taxable,         fmtMode)}</td>
              <td className={anomCls(i,'eco_igst',          tdM)}>{fmtVal(r.eco_igst,            fmtMode)}</td>
              <td className={anomCls(i,'eco_cgst',          tdM)}>{fmtVal(r.eco_cgst,            fmtMode)}</td>
              <td className={anomCls(i,'eco_sgst',          tdM)}>{fmtVal(r.eco_sgst,            fmtMode)}</td>
              {/* 15 u/s 9(5) */}
              <td className={anomCls(i,'s95_taxable',       tdB)}>{fmtVal(r.s95_taxable,         fmtMode)}</td>
              <td className={anomCls(i,'s95_igst',          tdM)}>{fmtVal(r.s95_igst,            fmtMode)}</td>
              <td className={anomCls(i,'s95_cgst',          tdM)}>{fmtVal(r.s95_cgst,            fmtMode)}</td>
              <td className={anomCls(i,'s95_sgst',          tdM)}>{fmtVal(r.s95_sgst,            fmtMode)}</td>
              {/* HSN Summary */}
              <td className={anomCls(i,'hsn_taxable',       tdB)}>{fmtVal(r.hsn_taxable,         fmtMode)}</td>
              <td className={anomCls(i,'hsn_igst',          tdM)}>{fmtVal(r.hsn_igst,            fmtMode)}</td>
              <td className={anomCls(i,'hsn_cgst',          tdM)}>{fmtVal(r.hsn_cgst,            fmtMode)}</td>
              <td className={anomCls(i,'hsn_sgst',          tdM)}>{fmtVal(r.hsn_sgst,            fmtMode)}</td>
              {/* Total Tax */}
              <td className="px-3 py-2.5 text-right font-mono text-blue-200 whitespace-nowrap border-l border-slate-800/60">{fmtVal(r.hsn_taxable,fmtMode)}</td>
              <td className="px-3 py-2.5 text-right font-mono font-bold text-blue-400 whitespace-nowrap">{fmtVal(r.hsn_igst,fmtMode)}</td>
              <td className="px-3 py-2.5 text-right font-mono font-bold text-blue-400 whitespace-nowrap">{fmtVal(r.hsn_cgst,fmtMode)}</td>
              <td className="px-3 py-2.5 text-right font-mono font-bold text-blue-400 whitespace-nowrap">{fmtVal(r.hsn_sgst,fmtMode)}</td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr className="bg-slate-800/50 border-t-2 border-slate-700">
            <td className="px-3 py-2.5 text-white font-bold text-xs">TOTAL</td>
            {/* 4A B2B */}
            <td className={ftB}>{fmtVal(sum('b2b_taxable'),fmtMode)}</td><td className={ftM}>{fmtVal(sum('b2b_igst'),fmtMode)}</td><td className={ftM}>{fmtVal(sum('b2b_cgst'),fmtMode)}</td><td className={ftM}>{fmtVal(sum('b2b_sgst'),fmtMode)}</td>
            {/* 4B RCM */}
            <td className={ftB}>{fmtVal(sum('b2b_rcm_taxable'),fmtMode)}</td><td className={ftM}>{fmtVal(sum('b2b_rcm_igst'),fmtMode)}</td><td className={ftM}>{fmtVal(sum('b2b_rcm_cgst'),fmtMode)}</td><td className={ftM}>{fmtVal(sum('b2b_rcm_sgst'),fmtMode)}</td>
            {/* B2CL */}
            <td className={ftB}>{fmtVal(sum('b2cl_taxable'),fmtMode)}</td><td className={ftM}>{fmtVal(sum('b2cl_igst'),fmtMode)}</td>
            {/* B2CS */}
            <td className={ftB}>{fmtVal(sum('b2cs_taxable'),fmtMode)}</td><td className={ftM}>{fmtVal(sum('b2cs_igst'),fmtMode)}</td><td className={ftM}>{fmtVal(sum('b2cs_cgst'),fmtMode)}</td><td className={ftM}>{fmtVal(sum('b2cs_sgst'),fmtMode)}</td>
            {/* NIL */}
            <td className={ftB}>{fmtVal(sum('nil_rated'),fmtMode)}</td><td className={ftM}>{fmtVal(sum('exempt'),fmtMode)}</td><td className={ftM}>{fmtVal(sum('non_gst'),fmtMode)}</td>
            {/* 6A */}
            <td className={ftB}>{fmtVal(sum('exp_expwp_taxable'),fmtMode)}</td><td className={ftM}>{fmtVal(sum('exp_expwp_igst'),fmtMode)}</td>
            <td className={ftB}>{fmtVal(sum('exp_expwop_taxable'),fmtMode)}</td>
            {/* 6B */}
            <td className={ftB}>{fmtVal(sum('sez_sezwp_taxable'),fmtMode)}</td><td className={ftM}>{fmtVal(sum('sez_sezwp_igst'),fmtMode)}</td>
            <td className={ftB}>{fmtVal(sum('sez_sezwop_taxable'),fmtMode)}</td>
            {/* 6C DE */}
            <td className={ftB}>{fmtVal(sum('de_taxable'),fmtMode)}</td><td className={ftM}>{fmtVal(sum('de_igst'),fmtMode)}</td><td className={ftM}>{fmtVal(sum('de_cgst'),fmtMode)}</td><td className={ftM}>{fmtVal(sum('de_sgst'),fmtMode)}</td>
            {/* CDNR */}
            <td className={ftB}>{fmtVal(sum('cdnr_taxable'),fmtMode)}</td><td className={ftM}>{fmtVal(sum('cdnr_igst'),fmtMode)}</td><td className={ftM}>{fmtVal(sum('cdnr_cgst'),fmtMode)}</td><td className={ftM}>{fmtVal(sum('cdnr_sgst'),fmtMode)}</td>
            {/* CDNUR */}
            <td className={ftB}>{fmtVal(sum('cdnur_taxable'),fmtMode)}</td><td className={ftM}>{fmtVal(sum('cdnur_igst'),fmtMode)}</td><td className={ftM}>{fmtVal(sum('cdnur_cgst'),fmtMode)}</td><td className={ftM}>{fmtVal(sum('cdnur_sgst'),fmtMode)}</td>
            {/* CDNRA */}
            <td className={ftB}>{fmtVal(sum('cdnra_taxable'),fmtMode)}</td><td className={ftM}>{fmtVal(sum('cdnra_igst'),fmtMode)}</td><td className={ftM}>{fmtVal(sum('cdnra_cgst'),fmtMode)}</td><td className={ftM}>{fmtVal(sum('cdnra_sgst'),fmtMode)}</td>
            {/* CDNURA */}
            <td className={ftB}>{fmtVal(sum('cdnura_taxable'),fmtMode)}</td><td className={ftM}>{fmtVal(sum('cdnura_igst'),fmtMode)}</td>
            {/* 9A Amendments */}
            <td className={ftB}>{fmtVal(sum('amend_b2b_taxable'),fmtMode)}</td><td className={ftM}>{fmtVal(sum('amend_b2b_igst'),fmtMode)}</td><td className={ftM}>{fmtVal(sum('amend_b2b_cgst'),fmtMode)}</td><td className={ftM}>{fmtVal(sum('amend_b2b_sgst'),fmtMode)}</td>
            <td className={ftB}>{fmtVal(sum('amend_b2cl_taxable'),fmtMode)}</td><td className={ftM}>{fmtVal(sum('amend_b2cl_igst'),fmtMode)}</td>
            <td className={ftB}>{fmtVal(sum('amend_exp_taxable'),fmtMode)}</td><td className={ftM}>{fmtVal(sum('amend_exp_igst'),fmtMode)}</td>
            <td className={ftB}>{fmtVal(sum('amend_sez_taxable'),fmtMode)}</td><td className={ftM}>{fmtVal(sum('amend_sez_igst'),fmtMode)}</td>
            <td className={ftB}>{fmtVal(sum('amend_de_taxable'),fmtMode)}</td><td className={ftM}>{fmtVal(sum('amend_de_igst'),fmtMode)}</td>
            {/* 10 B2CS Amend */}
            <td className={ftB}>{fmtVal(sum('amend_b2cs_taxable'),fmtMode)}</td><td className={ftM}>{fmtVal(sum('amend_b2cs_igst'),fmtMode)}</td><td className={ftM}>{fmtVal(sum('amend_b2cs_cgst'),fmtMode)}</td><td className={ftM}>{fmtVal(sum('amend_b2cs_sgst'),fmtMode)}</td>
            {/* 11A/11B */}
            <td className={ftB}>{fmtVal(sum('adv_recv_taxable'),fmtMode)}</td><td className={ftM}>{fmtVal(sum('adv_recv_igst'),fmtMode)}</td><td className={ftM}>{fmtVal(sum('adv_recv_cgst'),fmtMode)}</td><td className={ftM}>{fmtVal(sum('adv_recv_sgst'),fmtMode)}</td>
            <td className={ftB}>{fmtVal(sum('adv_adj_taxable'),fmtMode)}</td><td className={ftM}>{fmtVal(sum('adv_adj_igst'),fmtMode)}</td><td className={ftM}>{fmtVal(sum('adv_adj_cgst'),fmtMode)}</td><td className={ftM}>{fmtVal(sum('adv_adj_sgst'),fmtMode)}</td>
            {/* 14 ECO */}
            <td className={ftB}>{fmtVal(sum('eco_taxable'),fmtMode)}</td><td className={ftM}>{fmtVal(sum('eco_igst'),fmtMode)}</td><td className={ftM}>{fmtVal(sum('eco_cgst'),fmtMode)}</td><td className={ftM}>{fmtVal(sum('eco_sgst'),fmtMode)}</td>
            {/* 15 9(5) */}
            <td className={ftB}>{fmtVal(sum('s95_taxable'),fmtMode)}</td><td className={ftM}>{fmtVal(sum('s95_igst'),fmtMode)}</td><td className={ftM}>{fmtVal(sum('s95_cgst'),fmtMode)}</td><td className={ftM}>{fmtVal(sum('s95_sgst'),fmtMode)}</td>
            {/* HSN */}
            <td className={ftB}>{fmtVal(sum('hsn_taxable'),fmtMode)}</td><td className={ftM}>{fmtVal(sum('hsn_igst'),fmtMode)}</td><td className={ftM}>{fmtVal(sum('hsn_cgst'),fmtMode)}</td><td className={ftM}>{fmtVal(sum('hsn_sgst'),fmtMode)}</td>
            {/* Total */}
            <td className="px-3 py-2.5 text-right font-mono font-bold text-blue-200 text-sm whitespace-nowrap border-l border-slate-800/60">{fmtVal(sum('hsn_taxable'),fmtMode)}</td>
            <td className="px-3 py-2.5 text-right font-mono font-bold text-blue-400 text-sm whitespace-nowrap">{fmtVal(sum('hsn_igst'),fmtMode)}</td>
            <td className="px-3 py-2.5 text-right font-mono font-bold text-blue-400 text-sm whitespace-nowrap">{fmtVal(sum('hsn_cgst'),fmtMode)}</td>
            <td className="px-3 py-2.5 text-right font-mono font-bold text-blue-400 text-sm whitespace-nowrap">{fmtVal(sum('hsn_sgst'),fmtMode)}</td>
          </tr>
          {annualRow && (
            <tr className="border-t border-amber-600/30 bg-amber-500/5">
              <td className="px-3 py-2 text-amber-400 font-bold text-xs whitespace-nowrap">
                Annual (PDF){' '}
                <span className="text-[9px] font-normal text-amber-600">
                  {annualFile?.name?.slice(0,20)}{annualFile?.name?.length > 20 ? '…' : ''}
                </span>
              </td>
              {['b2b_taxable','b2b_igst','b2b_cgst','b2b_sgst',
                'b2b_rcm_taxable','b2b_rcm_igst','b2b_rcm_cgst','b2b_rcm_sgst',
                'b2cl_taxable','b2cl_igst',
                'b2cs_taxable','b2cs_igst','b2cs_cgst','b2cs_sgst',
                'nil_rated','exempt','non_gst',
                'exp_expwp_taxable','exp_expwp_igst','exp_expwop_taxable',
                'sez_sezwp_taxable','sez_sezwp_igst','sez_sezwop_taxable',
                'de_taxable','de_igst','de_cgst','de_sgst',
                'cdnr_taxable','cdnr_igst','cdnr_cgst','cdnr_sgst',
                'cdnur_taxable','cdnur_igst','cdnur_cgst','cdnur_sgst',
                'cdnra_taxable','cdnra_igst','cdnra_cgst','cdnra_sgst',
                'cdnura_taxable','cdnura_igst',
                'amend_b2b_taxable','amend_b2b_igst','amend_b2b_cgst','amend_b2b_sgst',
                'amend_b2cl_taxable','amend_b2cl_igst',
                'amend_exp_taxable','amend_exp_igst',
                'amend_sez_taxable','amend_sez_igst',
                'amend_de_taxable','amend_de_igst',
                'amend_b2cs_taxable','amend_b2cs_igst','amend_b2cs_cgst','amend_b2cs_sgst',
                'adv_recv_taxable','adv_recv_igst','adv_recv_cgst','adv_recv_sgst',
                'adv_adj_taxable','adv_adj_igst','adv_adj_cgst','adv_adj_sgst',
                'eco_taxable','eco_igst','eco_cgst','eco_sgst',
                's95_taxable','s95_igst','s95_cgst','s95_sgst',
                'hsn_taxable','hsn_igst','hsn_cgst','hsn_sgst',
                'hsn_taxable','hsn_igst','hsn_cgst','hsn_sgst'].map((k,idx) => (
                <td key={idx} className="px-3 py-2 text-right font-mono text-amber-300 whitespace-nowrap">
                  {fmtVal(annualRow[k], fmtMode)}
                </td>
              ))}
            </tr>
          )}
          {annualRow && (
            <tr className="border-t border-slate-700/60 bg-slate-900/60">
              <td className="px-3 py-2 text-slate-400 font-bold text-xs whitespace-nowrap italic">
                Difference <span className="text-[9px] font-normal text-slate-600 not-italic">(Annual − Total)</span>
              </td>
              {['b2b_taxable','b2b_igst','b2b_cgst','b2b_sgst',
                'b2b_rcm_taxable','b2b_rcm_igst','b2b_rcm_cgst','b2b_rcm_sgst',
                'b2cl_taxable','b2cl_igst',
                'b2cs_taxable','b2cs_igst','b2cs_cgst','b2cs_sgst',
                'nil_rated','exempt','non_gst',
                'exp_expwp_taxable','exp_expwp_igst','exp_expwop_taxable',
                'sez_sezwp_taxable','sez_sezwp_igst','sez_sezwop_taxable',
                'de_taxable','de_igst','de_cgst','de_sgst',
                'cdnr_taxable','cdnr_igst','cdnr_cgst','cdnr_sgst',
                'cdnur_taxable','cdnur_igst','cdnur_cgst','cdnur_sgst',
                'cdnra_taxable','cdnra_igst','cdnra_cgst','cdnra_sgst',
                'cdnura_taxable','cdnura_igst',
                'amend_b2b_taxable','amend_b2b_igst','amend_b2b_cgst','amend_b2b_sgst',
                'amend_b2cl_taxable','amend_b2cl_igst',
                'amend_exp_taxable','amend_exp_igst',
                'amend_sez_taxable','amend_sez_igst',
                'amend_de_taxable','amend_de_igst',
                'amend_b2cs_taxable','amend_b2cs_igst','amend_b2cs_cgst','amend_b2cs_sgst',
                'adv_recv_taxable','adv_recv_igst','adv_recv_cgst','adv_recv_sgst',
                'adv_adj_taxable','adv_adj_igst','adv_adj_cgst','adv_adj_sgst',
                'eco_taxable','eco_igst','eco_cgst','eco_sgst',
                's95_taxable','s95_igst','s95_cgst','s95_sgst',
                'hsn_taxable','hsn_igst','hsn_cgst','hsn_sgst',
                'hsn_taxable','hsn_igst','hsn_cgst','hsn_sgst'].map((k, idx) => {
                const dv = diffVal(k)
                return <td key={idx} className={diffCls(dv)}>{fmtDiff(dv)}</td>
              })}
            </tr>
          )}
        </tfoot>
      </table>
    </div>
  )
}

// ── GSTR-3B MOM table — 52-column format matching reference Excel ─────────────
function GSTR3BTable({ files, analyticsById, fmtMode, annualFileId3B, annualFile3B, annualExt3B }) {
  const filesWithData = files.filter((f) => analyticsById[f.id])
  if (filesWithData.length === 0) return null

  const buildRow = (f, ext) => {
    const nil_i  = ext.s5_nil_interstate    ?? null
    const nil_n  = ext.s5_nil_intrastate    ?? null
    const ng_i   = ext.s5_nongst_interstate ?? null
    const ng_n   = ext.s5_nongst_intrastate ?? null
    const lf_c   = ext.s51_latefee_cgst ?? null
    const lf_s   = ext.s51_latefee_sgst ?? null
    const p_itc_i = ext.itc_used_igst    ?? null
    const p_itc_c = ext.itc_used_cgst    ?? null
    const p_itc_s = ext.itc_used_sgst    ?? null
    const p_csh_i = ext.cash_paid_igst   ?? null
    const p_csh_c = ext.cash_paid_cgst   ?? null
    const p_csh_s = ext.cash_paid_sgst   ?? null
    const p_tot_i = (p_itc_i != null || p_csh_i != null) ? ((p_itc_i??0)+(p_csh_i??0)) : null
    const p_tot_c = (p_itc_c != null || p_csh_c != null) ? ((p_itc_c??0)+(p_csh_c??0)) : null
    const p_tot_s = (p_itc_s != null || p_csh_s != null) ? ((p_itc_s??0)+(p_csh_s??0)) : null
    return {
      period:           f.period || '—',
      // 3.1(a)
      a_taxable:        ext.taxable_sales     ?? null,
      a_igst:           ext.igst_on_sales     ?? null,
      a_cgst:           ext.cgst_on_sales     ?? null,
      a_sgst:           ext.sgst_on_sales     ?? null,
      a_cess:           ext.cess_on_sales     ?? null,
      // 3.1(b)
      b_taxable:        ext.zero_rated_sales  ?? null,
      b_igst:           ext.s31b_igst         ?? null,
      b_cgst:           null,
      b_sgst:           null,
      // 3.1(c)
      c_taxable:        ext.nil_rated_sales   ?? null,
      // 3.1(d)
      d_taxable:        ext.s31d_rcm_taxable  ?? null,
      d_igst:           ext.s31d_rcm_igst     ?? null,
      d_cgst:           ext.s31d_rcm_cgst     ?? null,
      d_sgst:           ext.s31d_rcm_sgst     ?? null,
      // 3.1(e)
      e_taxable:        ext.non_gst_sales     ?? null,
      // 3.1.1(i) ECO operator pays tax u/s 9(5)
      s311i_taxable:    ext.s311i_taxable     ?? null,
      s311i_igst:       ext.s311i_igst        ?? null,
      s311i_cgst:       ext.s311i_cgst        ?? null,
      s311i_sgst:       ext.s311i_sgst        ?? null,
      s311i_cess:       ext.s311i_cess        ?? null,
      // 3.1.1(ii) Registered person through ECO
      s311ii_taxable:   ext.s311ii_taxable    ?? null,
      // 3.2
      r2_unreg_tax:     ext.s32_unreg_taxable ?? null,
      r2_unreg_igst:    ext.s32_unreg_igst    ?? null,
      r2_comp_tax:      ext.s32_comp_taxable  ?? null,
      r2_uin_tax:       ext.s32_uin_taxable   ?? null,
      // 4(A)(1) Import of Goods
      itc_a1_igst:      ext.itc_a1_igst        ?? null,
      itc_a1_cgst:      ext.itc_a1_cgst        ?? null,
      itc_a1_sgst:      ext.itc_a1_sgst        ?? null,
      itc_a1_cess:      ext.itc_a1_cess        ?? null,
      // 4(A)(2) Import of Services
      itc_a2_igst:      ext.itc_a2_igst        ?? null,
      itc_a2_cgst:      ext.itc_a2_cgst        ?? null,
      itc_a2_sgst:      ext.itc_a2_sgst        ?? null,
      itc_a2_cess:      ext.itc_a2_cess        ?? null,
      // 4(A)(3) Inward RCM
      itc_a3_igst:      ext.itc_a3_igst        ?? null,
      itc_a3_cgst:      ext.itc_a3_cgst        ?? null,
      itc_a3_sgst:      ext.itc_a3_sgst        ?? null,
      itc_a3_cess:      ext.itc_a3_cess        ?? null,
      // 4(A)(4) ISD
      itc_a4_igst:      ext.itc_a4_igst        ?? null,
      itc_a4_cgst:      ext.itc_a4_cgst        ?? null,
      itc_a4_sgst:      ext.itc_a4_sgst        ?? null,
      itc_a4_cess:      ext.itc_a4_cess        ?? null,
      // 4(A)(5) All Other ITC
      itc_a5_igst:      ext.itc_a5_igst        ?? null,
      itc_a5_cgst:      ext.itc_a5_cgst        ?? null,
      itc_a5_sgst:      ext.itc_a5_sgst        ?? null,
      itc_a5_cess:      ext.itc_a5_cess        ?? null,
      // 4(A) Total Available
      itc_av_igst:      ext.itc_avail_igst     ?? null,
      itc_av_cgst:      ext.itc_avail_cgst     ?? null,
      itc_av_sgst:      ext.itc_avail_sgst     ?? null,
      itc_av_cess:      ext.itc_avail_cess     ?? null,
      // 4(B)(1) Rules 38,42,43 & s17(5)
      itc_b1_igst:      ext.itc_b1_igst        ?? null,
      itc_b1_cgst:      ext.itc_b1_cgst        ?? null,
      itc_b1_sgst:      ext.itc_b1_sgst        ?? null,
      itc_b1_cess:      ext.itc_b1_cess        ?? null,
      // 4(B)(2) Others
      itc_b2_igst:      ext.itc_b2_igst        ?? null,
      itc_b2_cgst:      ext.itc_b2_cgst        ?? null,
      itc_b2_sgst:      ext.itc_b2_sgst        ?? null,
      itc_b2_cess:      ext.itc_b2_cess        ?? null,
      // 4(B) Total Reversed
      itc_rv_igst:      ext.itc_reversed_igst  ?? null,
      itc_rv_cgst:      ext.itc_reversed_cgst  ?? null,
      itc_rv_sgst:      ext.itc_reversed_sgst  ?? null,
      itc_rv_cess:      ext.itc_rev_cess       ?? null,
      // 4(C) Net ITC
      itc_net_igst:     ext.itc_igst_available ?? null,
      itc_net_cgst:     ext.itc_cgst_available ?? null,
      itc_net_sgst:     ext.itc_sgst_available ?? null,
      itc_net_cess:     ext.itc_net_cess       ?? null,
      // 4(D)(1) ITC reclaimed reversed under 4(B)(2)
      itc_d1_igst:      ext.itc_d1_igst        ?? null,
      itc_d1_cgst:      ext.itc_d1_cgst        ?? null,
      itc_d1_sgst:      ext.itc_d1_sgst        ?? null,
      itc_d1_cess:      ext.itc_d1_cess        ?? null,
      // 4(D)(2) Ineligible u/s 16(4) & PoS rules
      itc_d2_igst:      ext.itc_d2_igst        ?? null,
      itc_d2_cgst:      ext.itc_d2_cgst        ?? null,
      itc_d2_sgst:      ext.itc_d2_sgst        ?? null,
      itc_d2_cess:      ext.itc_d2_cess        ?? null,
      // Sec 5 Nil/Exempt
      s5_nil_i:         nil_i,
      s5_nil_n:         nil_n,
      s5_nil_tot:       (nil_i != null || nil_n != null) ? ((nil_i??0)+(nil_n??0)) : null,
      // Sec 5 Non-GST
      s5_ng_i:          ng_i,
      s5_ng_n:          ng_n,
      s5_ng_tot:        (ng_i != null || ng_n != null) ? ((ng_i??0)+(ng_n??0)) : null,
      // 5.1 Interest
      int_igst:         ext.s51_int_igst  ?? null,
      int_cgst:         ext.s51_int_cgst  ?? null,
      int_sgst:         ext.s51_int_sgst  ?? null,
      int_cess:         ext.s51_int_cess  ?? null,
      // 5.1 Late Fee
      lf_cgst:          lf_c,
      lf_sgst:          lf_s,
      lf_tot:           (lf_c != null || lf_s != null) ? ((lf_c??0)+(lf_s??0)) : null,
      // Payment (6.1)
      pay_tot_igst:     p_tot_i,
      pay_tot_cgst:     p_tot_c,
      pay_tot_sgst:     p_tot_s,
      pay_itc_igst:     p_itc_i,
      pay_itc_cgst:     p_itc_c,
      pay_itc_sgst:     p_itc_s,
      pay_csh_igst:     p_csh_i,
      pay_csh_cgst:     p_csh_c,
      pay_csh_sgst:     p_csh_s,
    }
  }

  const rows = filesWithData.map((f) => buildRow(f, analyticsById[f.id]?.extracted_data || {}))
  const sum  = (key) => { const t = rows.reduce((s, r) => s + (r[key] ?? 0), 0); return t || null }

  const annualRow3B = (annualFile3B && annualExt3B) ? buildRow(annualFile3B, annualExt3B) : null

  const diffVal = (key) => {
    if (!annualRow3B) return null
    const d = (annualRow3B[key] ?? 0) - (sum(key) ?? 0)
    return Math.abs(d) < 0.01 ? 'NIL' : d
  }
  const fmtDiff = (v) => {
    if (v === null || v === undefined) return '—'
    if (v === 'NIL') return 'Nil'
    return fmtVal(v, fmtMode)
  }
  const diffCls = (v) => {
    const base = 'px-2 py-2 text-right font-mono whitespace-nowrap text-[10px]'
    if (v === null || v === 'NIL') return `${base} text-emerald-600`
    return v > 0 ? `${base} text-amber-400 font-semibold` : `${base} text-red-400 font-semibold`
  }

  const anomCls = (rowIdx, key, base) => {
    if (rowIdx === 0) return base
    return _isAnom(rows[rowIdx][key], rows[rowIdx - 1][key])
      ? `${base} bg-amber-500/10 ring-1 ring-inset ring-amber-500/35`
      : base
  }

  // Styling helpers
  const thG  = 'px-2 py-2 text-center text-[9px] font-bold text-slate-200 uppercase tracking-wider border-b border-slate-700 whitespace-nowrap'
  const thS  = 'px-2 py-1.5 text-right text-[9px] font-semibold text-slate-500 whitespace-nowrap'
  const tdM  = 'px-2 py-2 text-right font-mono text-[10px] text-slate-300 whitespace-nowrap'
  const tdB  = 'px-2 py-2 text-right font-mono text-[10px] text-slate-300 whitespace-nowrap border-l-2 border-slate-700'
  const ftM  = 'px-2 py-2 text-right font-mono text-[10px] font-bold text-white whitespace-nowrap'
  const ftB  = 'px-2 py-2 text-right font-mono text-[10px] font-bold text-white whitespace-nowrap border-l-2 border-slate-700'
  const v    = (r, k) => fmtVal(r[k], fmtMode)
  const sv   = (k)    => fmtVal(sum(k), fmtMode)
  const td   = (ri, k, border) => border ? anomCls(ri, k, tdB) : anomCls(ri, k, tdM)

  // Group header colours
  const colours = {
    a: 'text-emerald-300', b: 'text-sky-300',    c: 'text-slate-300',
    d: 'text-orange-300',  e: 'text-slate-300',   r2: 'text-purple-300',
    itc: 'text-violet-300', s5: 'text-teal-300',
    int: 'text-rose-300',   lf: 'text-rose-300',  pay: 'text-amber-300',
    s311i: 'text-cyan-300', s311ii: 'text-cyan-200',
    // ITC sub-groups (bifurcated exactly as per GSTR-3B Section 4)
    itcA:  'text-violet-300',   // 4(A)(1-5) sub-items
    itcAT: 'text-violet-200',   // 4(A) Total Available
    itcB:  'text-fuchsia-300',  // 4(B)(1-2) sub-items
    itcBT: 'text-fuchsia-200',  // 4(B) Total Reversed
    itcC:  'text-indigo-300',   // 4(C) Net ITC
    itcD1: 'text-blue-300',     // 4(D)(1) Reclaimed
    itcD2: 'text-red-300',      // 4(D)(2) Ineligible
  }

  return (
    <div className="overflow-x-auto rounded-xl border border-slate-800">
      <table className="text-xs border-collapse" style={{ minWidth: '3200px' }}>
        <thead>
          {/* Row 1: Group headers */}
          <tr className="bg-slate-900 border-b border-slate-700">
            <th rowSpan={2} className="sticky left-0 z-10 bg-slate-900 px-3 py-2 text-left text-[10px] font-bold text-slate-400 uppercase tracking-wider whitespace-nowrap align-bottom border-b border-r border-slate-700 min-w-[120px]">
              PERIOD
            </th>
            <th colSpan={5} className={`${thG} border-l-2 border-slate-700 ${colours.a}`}>3.1(a) Taxable</th>
            <th colSpan={4} className={`${thG} border-l-2 border-slate-700 ${colours.b}`}>3.1(b) Zero Rated</th>
            <th colSpan={1} className={`${thG} border-l-2 border-slate-700 ${colours.c}`}>3.1(c) Nil/Exempt</th>
            <th colSpan={4} className={`${thG} border-l-2 border-slate-700 ${colours.d}`}>3.1(d) RCM</th>
            <th colSpan={1} className={`${thG} border-l-2 border-slate-700 ${colours.e}`}>3.1(e)</th>
            <th colSpan={5} className={`${thG} border-l-2 border-slate-700 ${colours.s311i}`}>3.1.1(i) ECO-9(5)</th>
            <th colSpan={1} className={`${thG} border-l-2 border-slate-700 ${colours.s311ii}`}>3.1.1(ii)</th>
            <th colSpan={4} className={`${thG} border-l-2 border-slate-700 ${colours.r2}`}>3.2 Interstate</th>
            <th colSpan={4} className={`${thG} border-l-2 border-slate-700 ${colours.itcA}`}>4(A)(1) Imp Goods</th>
            <th colSpan={4} className={`${thG} border-l-2 border-slate-700 ${colours.itcA}`}>4(A)(2) Imp Svcs</th>
            <th colSpan={4} className={`${thG} border-l-2 border-slate-700 ${colours.itcA}`}>4(A)(3) RCM Inward</th>
            <th colSpan={4} className={`${thG} border-l-2 border-slate-700 ${colours.itcA}`}>4(A)(4) ISD</th>
            <th colSpan={4} className={`${thG} border-l-2 border-slate-700 ${colours.itcA}`}>4(A)(5) Other ITC</th>
            <th colSpan={4} className={`${thG} border-l-2 border-slate-700 ${colours.itcAT}`}>4(A) Total Avail</th>
            <th colSpan={4} className={`${thG} border-l-2 border-slate-700 ${colours.itcB}`}>4(B)(1) Rules</th>
            <th colSpan={4} className={`${thG} border-l-2 border-slate-700 ${colours.itcB}`}>4(B)(2) Others</th>
            <th colSpan={4} className={`${thG} border-l-2 border-slate-700 ${colours.itcBT}`}>4(B) Total Rev</th>
            <th colSpan={4} className={`${thG} border-l-2 border-slate-700 ${colours.itcC}`}>4(C) Net ITC</th>
            <th colSpan={4} className={`${thG} border-l-2 border-slate-700 ${colours.itcD1}`}>4(D)(1) Reclaimed</th>
            <th colSpan={4} className={`${thG} border-l-2 border-slate-700 ${colours.itcD2}`}>4(D)(2) Ineligible</th>
            <th colSpan={3} className={`${thG} border-l-2 border-slate-700 ${colours.s5}`}>Sec 5 – Nil/Exempt</th>
            <th colSpan={3} className={`${thG} border-l-2 border-slate-700 ${colours.s5}`}>Sec 5 – Non-GST</th>
            <th colSpan={4} className={`${thG} border-l-2 border-slate-700 ${colours.int}`}>5.1 Interest</th>
            <th colSpan={3} className={`${thG} border-l-2 border-slate-700 ${colours.lf}`}>5.1 Late Fee</th>
            <th colSpan={9} className={`${thG} border-l-2 border-slate-700 ${colours.pay}`}>Payment (6.1)</th>
          </tr>
          {/* Row 2: Sub-headers */}
          <tr className="bg-slate-900/80 border-b border-slate-800">
            {/* 3.1(a) */}
            <th className={`${thS} border-l-2 border-slate-700 ${colours.a}`}>Taxable</th>
            <th className={`${thS} ${colours.a}`}>IGST</th>
            <th className={`${thS} ${colours.a}`}>CGST</th>
            <th className={`${thS} ${colours.a}`}>SGST</th>
            <th className={`${thS} ${colours.a}`}>Cess</th>
            {/* 3.1(b) */}
            <th className={`${thS} border-l-2 border-slate-700 ${colours.b}`}>Taxable</th>
            <th className={`${thS} ${colours.b}`}>IGST</th>
            <th className={`${thS} ${colours.b}`}>CGST</th>
            <th className={`${thS} ${colours.b}`}>SGST</th>
            {/* 3.1(c) */}
            <th className={`${thS} border-l-2 border-slate-700 ${colours.c}`}>Taxable</th>
            {/* 3.1(d) */}
            <th className={`${thS} border-l-2 border-slate-700 ${colours.d}`}>Taxable</th>
            <th className={`${thS} ${colours.d}`}>IGST</th>
            <th className={`${thS} ${colours.d}`}>CGST</th>
            <th className={`${thS} ${colours.d}`}>SGST</th>
            {/* 3.1(e) */}
            <th className={`${thS} border-l-2 border-slate-700 ${colours.e}`}>Taxable</th>
            {/* 3.1.1(i) */}
            <th className={`${thS} border-l-2 border-slate-700 ${colours.s311i}`}>Taxable</th>
            <th className={`${thS} ${colours.s311i}`}>IGST</th>
            <th className={`${thS} ${colours.s311i}`}>CGST</th>
            <th className={`${thS} ${colours.s311i}`}>SGST</th>
            <th className={`${thS} ${colours.s311i}`}>Cess</th>
            {/* 3.1.1(ii) */}
            <th className={`${thS} border-l-2 border-slate-700 ${colours.s311ii}`}>Taxable</th>
            {/* 3.2 */}
            <th className={`${thS} border-l-2 border-slate-700 ${colours.r2}`}>Unreg Tax</th>
            <th className={`${thS} ${colours.r2}`}>Unreg IGST</th>
            <th className={`${thS} ${colours.r2}`}>Comp Tax</th>
            <th className={`${thS} ${colours.r2}`}>UIN Tax</th>
            {/* 4(A)(1-5) + Total + 4(B)(1-2) + Total + 4(C) + 4(D)(1) + 4(D)(2) */}
            {[colours.itcA,colours.itcA,colours.itcA,colours.itcA,colours.itcA,colours.itcAT,colours.itcB,colours.itcB,colours.itcBT,colours.itcC,colours.itcD1,colours.itcD2].map((c,i) => (
              <React.Fragment key={i}>
                <th className={`${thS} border-l-2 border-slate-700 ${c}`}>IGST</th>
                <th className={`${thS} ${c}`}>CGST</th>
                <th className={`${thS} ${c}`}>SGST</th>
                <th className={`${thS} ${c}`}>Cess</th>
              </React.Fragment>
            ))}
            {/* Sec 5 Nil/Exempt */}
            <th className={`${thS} border-l-2 border-slate-700 ${colours.s5}`}>Inter-State</th>
            <th className={`${thS} ${colours.s5}`}>Intra-State</th>
            <th className={`${thS} ${colours.s5}`}>Total</th>
            {/* Sec 5 Non-GST */}
            <th className={`${thS} border-l-2 border-slate-700 ${colours.s5}`}>Inter-State</th>
            <th className={`${thS} ${colours.s5}`}>Intra-State</th>
            <th className={`${thS} ${colours.s5}`}>Total</th>
            {/* 5.1 Interest */}
            <th className={`${thS} border-l-2 border-slate-700 ${colours.int}`}>IGST</th>
            <th className={`${thS} ${colours.int}`}>CGST</th>
            <th className={`${thS} ${colours.int}`}>SGST</th>
            <th className={`${thS} ${colours.int}`}>Cess</th>
            {/* 5.1 Late Fee */}
            <th className={`${thS} border-l-2 border-slate-700 ${colours.lf}`}>CGST</th>
            <th className={`${thS} ${colours.lf}`}>SGST</th>
            <th className={`${thS} ${colours.lf}`}>Total</th>
            {/* Payment (6.1) */}
            <th className={`${thS} border-l-2 border-slate-700 ${colours.pay}`}>Total IGST</th>
            <th className={`${thS} ${colours.pay}`}>Total CGST</th>
            <th className={`${thS} ${colours.pay}`}>Total SGST</th>
            <th className={`${thS} ${colours.pay}`}>ITC IGST</th>
            <th className={`${thS} ${colours.pay}`}>ITC CGST</th>
            <th className={`${thS} ${colours.pay}`}>ITC SGST</th>
            <th className={`${thS} ${colours.pay}`}>Cash IGST</th>
            <th className={`${thS} ${colours.pay}`}>Cash CGST</th>
            <th className={`${thS} ${colours.pay}`}>Cash SGST</th>
          </tr>
        </thead>

        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-b border-slate-800/50 hover:bg-slate-800/20 transition-colors">
              <td className="sticky left-0 z-10 bg-slate-950 px-3 py-2 text-slate-300 font-medium whitespace-nowrap border-r border-slate-800 text-[10px]">{r.period}</td>
              {/* 3.1(a) */}
              <td className={td(i,'a_taxable',true)}>{v(r,'a_taxable')}</td>
              <td className={td(i,'a_igst',false)}>{v(r,'a_igst')}</td>
              <td className={td(i,'a_cgst',false)}>{v(r,'a_cgst')}</td>
              <td className={td(i,'a_sgst',false)}>{v(r,'a_sgst')}</td>
              <td className={td(i,'a_cess',false)}>{v(r,'a_cess')}</td>
              {/* 3.1(b) */}
              <td className={td(i,'b_taxable',true)}>{v(r,'b_taxable')}</td>
              <td className={td(i,'b_igst',false)}>{v(r,'b_igst')}</td>
              <td className={tdM}>{v(r,'b_cgst')}</td>
              <td className={tdM}>{v(r,'b_sgst')}</td>
              {/* 3.1(c) */}
              <td className={td(i,'c_taxable',true)}>{v(r,'c_taxable')}</td>
              {/* 3.1(d) */}
              <td className={td(i,'d_taxable',true)}>{v(r,'d_taxable')}</td>
              <td className={td(i,'d_igst',false)}>{v(r,'d_igst')}</td>
              <td className={td(i,'d_cgst',false)}>{v(r,'d_cgst')}</td>
              <td className={td(i,'d_sgst',false)}>{v(r,'d_sgst')}</td>
              {/* 3.1(e) */}
              <td className={td(i,'e_taxable',true)}>{v(r,'e_taxable')}</td>
              {/* 3.1.1(i) */}
              <td className={td(i,'s311i_taxable',true)}>{v(r,'s311i_taxable')}</td>
              <td className={td(i,'s311i_igst',false)}>{v(r,'s311i_igst')}</td>
              <td className={td(i,'s311i_cgst',false)}>{v(r,'s311i_cgst')}</td>
              <td className={td(i,'s311i_sgst',false)}>{v(r,'s311i_sgst')}</td>
              <td className={td(i,'s311i_cess',false)}>{v(r,'s311i_cess')}</td>
              {/* 3.1.1(ii) */}
              <td className={td(i,'s311ii_taxable',true)}>{v(r,'s311ii_taxable')}</td>
              {/* 3.2 */}
              <td className={td(i,'r2_unreg_tax',true)}>{v(r,'r2_unreg_tax')}</td>
              <td className={td(i,'r2_unreg_igst',false)}>{v(r,'r2_unreg_igst')}</td>
              <td className={td(i,'r2_comp_tax',false)}>{v(r,'r2_comp_tax')}</td>
              <td className={td(i,'r2_uin_tax',false)}>{v(r,'r2_uin_tax')}</td>
              {/* 4(A)(1) Imp Goods */}
              <td className={td(i,'itc_a1_igst',true)}>{v(r,'itc_a1_igst')}</td><td className={tdM}>{v(r,'itc_a1_cgst')}</td><td className={tdM}>{v(r,'itc_a1_sgst')}</td><td className={tdM}>{v(r,'itc_a1_cess')}</td>
              {/* 4(A)(2) Imp Svcs */}
              <td className={td(i,'itc_a2_igst',true)}>{v(r,'itc_a2_igst')}</td><td className={tdM}>{v(r,'itc_a2_cgst')}</td><td className={tdM}>{v(r,'itc_a2_sgst')}</td><td className={tdM}>{v(r,'itc_a2_cess')}</td>
              {/* 4(A)(3) RCM Inward */}
              <td className={td(i,'itc_a3_igst',true)}>{v(r,'itc_a3_igst')}</td><td className={tdM}>{v(r,'itc_a3_cgst')}</td><td className={tdM}>{v(r,'itc_a3_sgst')}</td><td className={tdM}>{v(r,'itc_a3_cess')}</td>
              {/* 4(A)(4) ISD */}
              <td className={td(i,'itc_a4_igst',true)}>{v(r,'itc_a4_igst')}</td><td className={tdM}>{v(r,'itc_a4_cgst')}</td><td className={tdM}>{v(r,'itc_a4_sgst')}</td><td className={tdM}>{v(r,'itc_a4_cess')}</td>
              {/* 4(A)(5) Other ITC */}
              <td className={td(i,'itc_a5_igst',true)}>{v(r,'itc_a5_igst')}</td><td className={tdM}>{v(r,'itc_a5_cgst')}</td><td className={tdM}>{v(r,'itc_a5_sgst')}</td><td className={tdM}>{v(r,'itc_a5_cess')}</td>
              {/* 4(A) Total Available */}
              <td className={td(i,'itc_av_igst',true)}>{v(r,'itc_av_igst')}</td><td className={tdM}>{v(r,'itc_av_cgst')}</td><td className={tdM}>{v(r,'itc_av_sgst')}</td><td className={tdM}>{v(r,'itc_av_cess')}</td>
              {/* 4(B)(1) Rules */}
              <td className={td(i,'itc_b1_igst',true)}>{v(r,'itc_b1_igst')}</td><td className={tdM}>{v(r,'itc_b1_cgst')}</td><td className={tdM}>{v(r,'itc_b1_sgst')}</td><td className={tdM}>{v(r,'itc_b1_cess')}</td>
              {/* 4(B)(2) Others */}
              <td className={td(i,'itc_b2_igst',true)}>{v(r,'itc_b2_igst')}</td><td className={tdM}>{v(r,'itc_b2_cgst')}</td><td className={tdM}>{v(r,'itc_b2_sgst')}</td><td className={tdM}>{v(r,'itc_b2_cess')}</td>
              {/* 4(B) Total Reversed */}
              <td className={td(i,'itc_rv_igst',true)}>{v(r,'itc_rv_igst')}</td><td className={tdM}>{v(r,'itc_rv_cgst')}</td><td className={tdM}>{v(r,'itc_rv_sgst')}</td><td className={tdM}>{v(r,'itc_rv_cess')}</td>
              {/* 4(C) Net ITC */}
              <td className={td(i,'itc_net_igst',true)}>{v(r,'itc_net_igst')}</td><td className={tdM}>{v(r,'itc_net_cgst')}</td><td className={tdM}>{v(r,'itc_net_sgst')}</td><td className={tdM}>{v(r,'itc_net_cess')}</td>
              {/* 4(D)(1) Reclaimed */}
              <td className={td(i,'itc_d1_igst',true)}>{v(r,'itc_d1_igst')}</td><td className={tdM}>{v(r,'itc_d1_cgst')}</td><td className={tdM}>{v(r,'itc_d1_sgst')}</td><td className={tdM}>{v(r,'itc_d1_cess')}</td>
              {/* 4(D)(2) Ineligible */}
              <td className={td(i,'itc_d2_igst',true)}>{v(r,'itc_d2_igst')}</td><td className={tdM}>{v(r,'itc_d2_cgst')}</td><td className={tdM}>{v(r,'itc_d2_sgst')}</td><td className={tdM}>{v(r,'itc_d2_cess')}</td>
              {/* Sec 5 Nil/Exempt */}
              <td className={td(i,'s5_nil_i',true)}>{v(r,'s5_nil_i')}</td>
              <td className={td(i,'s5_nil_n',false)}>{v(r,'s5_nil_n')}</td>
              <td className={td(i,'s5_nil_tot',false)}>{v(r,'s5_nil_tot')}</td>
              {/* Sec 5 Non-GST */}
              <td className={td(i,'s5_ng_i',true)}>{v(r,'s5_ng_i')}</td>
              <td className={td(i,'s5_ng_n',false)}>{v(r,'s5_ng_n')}</td>
              <td className={td(i,'s5_ng_tot',false)}>{v(r,'s5_ng_tot')}</td>
              {/* 5.1 Interest */}
              <td className={td(i,'int_igst',true)}>{v(r,'int_igst')}</td>
              <td className={td(i,'int_cgst',false)}>{v(r,'int_cgst')}</td>
              <td className={td(i,'int_sgst',false)}>{v(r,'int_sgst')}</td>
              <td className={td(i,'int_cess',false)}>{v(r,'int_cess')}</td>
              {/* 5.1 Late Fee */}
              <td className={td(i,'lf_cgst',true)}>{v(r,'lf_cgst')}</td>
              <td className={td(i,'lf_sgst',false)}>{v(r,'lf_sgst')}</td>
              <td className={td(i,'lf_tot',false)}>{v(r,'lf_tot')}</td>
              {/* Payment (6.1) */}
              <td className={td(i,'pay_tot_igst',true)}>{v(r,'pay_tot_igst')}</td>
              <td className={td(i,'pay_tot_cgst',false)}>{v(r,'pay_tot_cgst')}</td>
              <td className={td(i,'pay_tot_sgst',false)}>{v(r,'pay_tot_sgst')}</td>
              <td className={td(i,'pay_itc_igst',false)}>{v(r,'pay_itc_igst')}</td>
              <td className={td(i,'pay_itc_cgst',false)}>{v(r,'pay_itc_cgst')}</td>
              <td className={td(i,'pay_itc_sgst',false)}>{v(r,'pay_itc_sgst')}</td>
              <td className={td(i,'pay_csh_igst',false)}>{v(r,'pay_csh_igst')}</td>
              <td className={td(i,'pay_csh_cgst',false)}>{v(r,'pay_csh_cgst')}</td>
              <td className={td(i,'pay_csh_sgst',false)}>{v(r,'pay_csh_sgst')}</td>
            </tr>
          ))}
        </tbody>

        <tfoot>
          <tr className="bg-slate-800/60 border-t-2 border-slate-600">
            <td className="sticky left-0 z-10 bg-slate-800 px-3 py-2 text-white font-bold text-xs border-r border-slate-700">TOTAL</td>
            {/* 3.1(a) */}
            <td className={ftB}>{sv('a_taxable')}</td><td className={ftM}>{sv('a_igst')}</td><td className={ftM}>{sv('a_cgst')}</td><td className={ftM}>{sv('a_sgst')}</td><td className={ftM}>{sv('a_cess')}</td>
            {/* 3.1(b) */}
            <td className={ftB}>{sv('b_taxable')}</td><td className={ftM}>{sv('b_igst')}</td><td className={ftM}>—</td><td className={ftM}>—</td>
            {/* 3.1(c) */}
            <td className={ftB}>{sv('c_taxable')}</td>
            {/* 3.1(d) */}
            <td className={ftB}>{sv('d_taxable')}</td><td className={ftM}>{sv('d_igst')}</td><td className={ftM}>{sv('d_cgst')}</td><td className={ftM}>{sv('d_sgst')}</td>
            {/* 3.1(e) */}
            <td className={ftB}>{sv('e_taxable')}</td>
            {/* 3.1.1(i) */}
            <td className={ftB}>{sv('s311i_taxable')}</td><td className={ftM}>{sv('s311i_igst')}</td><td className={ftM}>{sv('s311i_cgst')}</td><td className={ftM}>{sv('s311i_sgst')}</td><td className={ftM}>{sv('s311i_cess')}</td>
            {/* 3.1.1(ii) */}
            <td className={ftB}>{sv('s311ii_taxable')}</td>
            {/* 3.2 */}
            <td className={ftB}>{sv('r2_unreg_tax')}</td><td className={ftM}>{sv('r2_unreg_igst')}</td><td className={ftM}>{sv('r2_comp_tax')}</td><td className={ftM}>{sv('r2_uin_tax')}</td>
            {/* 4(A)(1) */}<td className={ftB}>{sv('itc_a1_igst')}</td><td className={ftM}>{sv('itc_a1_cgst')}</td><td className={ftM}>{sv('itc_a1_sgst')}</td><td className={ftM}>{sv('itc_a1_cess')}</td>
            {/* 4(A)(2) */}<td className={ftB}>{sv('itc_a2_igst')}</td><td className={ftM}>{sv('itc_a2_cgst')}</td><td className={ftM}>{sv('itc_a2_sgst')}</td><td className={ftM}>{sv('itc_a2_cess')}</td>
            {/* 4(A)(3) */}<td className={ftB}>{sv('itc_a3_igst')}</td><td className={ftM}>{sv('itc_a3_cgst')}</td><td className={ftM}>{sv('itc_a3_sgst')}</td><td className={ftM}>{sv('itc_a3_cess')}</td>
            {/* 4(A)(4) */}<td className={ftB}>{sv('itc_a4_igst')}</td><td className={ftM}>{sv('itc_a4_cgst')}</td><td className={ftM}>{sv('itc_a4_sgst')}</td><td className={ftM}>{sv('itc_a4_cess')}</td>
            {/* 4(A)(5) */}<td className={ftB}>{sv('itc_a5_igst')}</td><td className={ftM}>{sv('itc_a5_cgst')}</td><td className={ftM}>{sv('itc_a5_sgst')}</td><td className={ftM}>{sv('itc_a5_cess')}</td>
            {/* 4(A) Tot*/}<td className={ftB}>{sv('itc_av_igst')}</td><td className={ftM}>{sv('itc_av_cgst')}</td><td className={ftM}>{sv('itc_av_sgst')}</td><td className={ftM}>{sv('itc_av_cess')}</td>
            {/* 4(B)(1) */}<td className={ftB}>{sv('itc_b1_igst')}</td><td className={ftM}>{sv('itc_b1_cgst')}</td><td className={ftM}>{sv('itc_b1_sgst')}</td><td className={ftM}>{sv('itc_b1_cess')}</td>
            {/* 4(B)(2) */}<td className={ftB}>{sv('itc_b2_igst')}</td><td className={ftM}>{sv('itc_b2_cgst')}</td><td className={ftM}>{sv('itc_b2_sgst')}</td><td className={ftM}>{sv('itc_b2_cess')}</td>
            {/* 4(B) Tot*/}<td className={ftB}>{sv('itc_rv_igst')}</td><td className={ftM}>{sv('itc_rv_cgst')}</td><td className={ftM}>{sv('itc_rv_sgst')}</td><td className={ftM}>{sv('itc_rv_cess')}</td>
            {/* 4(C)    */}<td className={ftB}>{sv('itc_net_igst')}</td><td className={ftM}>{sv('itc_net_cgst')}</td><td className={ftM}>{sv('itc_net_sgst')}</td><td className={ftM}>{sv('itc_net_cess')}</td>
            {/* 4(D)(1) */}<td className={ftB}>{sv('itc_d1_igst')}</td><td className={ftM}>{sv('itc_d1_cgst')}</td><td className={ftM}>{sv('itc_d1_sgst')}</td><td className={ftM}>{sv('itc_d1_cess')}</td>
            {/* 4(D)(2) */}<td className={ftB}>{sv('itc_d2_igst')}</td><td className={ftM}>{sv('itc_d2_cgst')}</td><td className={ftM}>{sv('itc_d2_sgst')}</td><td className={ftM}>{sv('itc_d2_cess')}</td>
            {/* Sec 5 */}
            <td className={ftB}>{sv('s5_nil_i')}</td><td className={ftM}>{sv('s5_nil_n')}</td><td className={ftM}>{sv('s5_nil_tot')}</td>
            <td className={ftB}>{sv('s5_ng_i')}</td><td className={ftM}>{sv('s5_ng_n')}</td><td className={ftM}>{sv('s5_ng_tot')}</td>
            {/* Interest */}
            <td className={ftB}>{sv('int_igst')}</td><td className={ftM}>{sv('int_cgst')}</td><td className={ftM}>{sv('int_sgst')}</td><td className={ftM}>{sv('int_cess')}</td>
            {/* Late Fee */}
            <td className={ftB}>{sv('lf_cgst')}</td><td className={ftM}>{sv('lf_sgst')}</td><td className={ftM}>{sv('lf_tot')}</td>
            {/* Payment */}
            <td className={ftB}>{sv('pay_tot_igst')}</td><td className={ftM}>{sv('pay_tot_cgst')}</td><td className={ftM}>{sv('pay_tot_sgst')}</td>
            <td className={ftM}>{sv('pay_itc_igst')}</td><td className={ftM}>{sv('pay_itc_cgst')}</td><td className={ftM}>{sv('pay_itc_sgst')}</td>
            <td className={ftM}>{sv('pay_csh_igst')}</td><td className={ftM}>{sv('pay_csh_cgst')}</td><td className={ftM}>{sv('pay_csh_sgst')}</td>
          </tr>
          {annualRow3B && (
            <tr className="border-t border-amber-600/30 bg-amber-500/5">
              <td className="sticky left-0 z-10 bg-amber-950/40 px-3 py-2 text-amber-400 font-bold text-xs whitespace-nowrap border-r border-slate-800">
                Annual (PDF){' '}
                <span className="text-[9px] font-normal text-amber-600">
                  {annualFile3B?.name?.slice(0,20)}{annualFile3B?.name?.length > 20 ? '…' : ''}
                </span>
              </td>
              {['a_taxable','a_igst','a_cgst','a_sgst','a_cess',
                'b_taxable','b_igst','b_cgst','b_sgst',
                'c_taxable',
                'd_taxable','d_igst','d_cgst','d_sgst',
                'e_taxable',
                's311i_taxable','s311i_igst','s311i_cgst','s311i_sgst','s311i_cess',
                's311ii_taxable',
                'r2_unreg_tax','r2_unreg_igst','r2_comp_tax','r2_uin_tax',
                'itc_a1_igst','itc_a1_cgst','itc_a1_sgst','itc_a1_cess',
                'itc_a2_igst','itc_a2_cgst','itc_a2_sgst','itc_a2_cess',
                'itc_a3_igst','itc_a3_cgst','itc_a3_sgst','itc_a3_cess',
                'itc_a4_igst','itc_a4_cgst','itc_a4_sgst','itc_a4_cess',
                'itc_a5_igst','itc_a5_cgst','itc_a5_sgst','itc_a5_cess',
                'itc_av_igst','itc_av_cgst','itc_av_sgst','itc_av_cess',
                'itc_b1_igst','itc_b1_cgst','itc_b1_sgst','itc_b1_cess',
                'itc_b2_igst','itc_b2_cgst','itc_b2_sgst','itc_b2_cess',
                'itc_rv_igst','itc_rv_cgst','itc_rv_sgst','itc_rv_cess',
                'itc_net_igst','itc_net_cgst','itc_net_sgst','itc_net_cess',
                'itc_d1_igst','itc_d1_cgst','itc_d1_sgst','itc_d1_cess',
                'itc_d2_igst','itc_d2_cgst','itc_d2_sgst','itc_d2_cess',
                's5_nil_i','s5_nil_n','s5_nil_tot',
                's5_ng_i','s5_ng_n','s5_ng_tot',
                'int_igst','int_cgst','int_sgst','int_cess',
                'lf_cgst','lf_sgst','lf_tot',
                'pay_tot_igst','pay_tot_cgst','pay_tot_sgst',
                'pay_itc_igst','pay_itc_cgst','pay_itc_sgst',
                'pay_csh_igst','pay_csh_cgst','pay_csh_sgst',
              ].map((k, idx) => (
                <td key={idx} className="px-2 py-2 text-right font-mono text-amber-300 whitespace-nowrap text-[10px]">
                  {fmtVal(annualRow3B[k], fmtMode)}
                </td>
              ))}
            </tr>
          )}
          {annualRow3B && (
            <tr className="border-t border-slate-700/60 bg-slate-900/60">
              <td className="sticky left-0 z-10 bg-slate-950 px-3 py-2 text-slate-400 font-bold text-xs whitespace-nowrap italic border-r border-slate-800">
                Difference <span className="text-[9px] font-normal text-slate-600 not-italic">(Annual − Total)</span>
              </td>
              {['a_taxable','a_igst','a_cgst','a_sgst','a_cess',
                'b_taxable','b_igst','b_cgst','b_sgst',
                'c_taxable',
                'd_taxable','d_igst','d_cgst','d_sgst',
                'e_taxable',
                's311i_taxable','s311i_igst','s311i_cgst','s311i_sgst','s311i_cess',
                's311ii_taxable',
                'r2_unreg_tax','r2_unreg_igst','r2_comp_tax','r2_uin_tax',
                'itc_a1_igst','itc_a1_cgst','itc_a1_sgst','itc_a1_cess',
                'itc_a2_igst','itc_a2_cgst','itc_a2_sgst','itc_a2_cess',
                'itc_a3_igst','itc_a3_cgst','itc_a3_sgst','itc_a3_cess',
                'itc_a4_igst','itc_a4_cgst','itc_a4_sgst','itc_a4_cess',
                'itc_a5_igst','itc_a5_cgst','itc_a5_sgst','itc_a5_cess',
                'itc_av_igst','itc_av_cgst','itc_av_sgst','itc_av_cess',
                'itc_b1_igst','itc_b1_cgst','itc_b1_sgst','itc_b1_cess',
                'itc_b2_igst','itc_b2_cgst','itc_b2_sgst','itc_b2_cess',
                'itc_rv_igst','itc_rv_cgst','itc_rv_sgst','itc_rv_cess',
                'itc_net_igst','itc_net_cgst','itc_net_sgst','itc_net_cess',
                'itc_d1_igst','itc_d1_cgst','itc_d1_sgst','itc_d1_cess',
                'itc_d2_igst','itc_d2_cgst','itc_d2_sgst','itc_d2_cess',
                's5_nil_i','s5_nil_n','s5_nil_tot',
                's5_ng_i','s5_ng_n','s5_ng_tot',
                'int_igst','int_cgst','int_sgst','int_cess',
                'lf_cgst','lf_sgst','lf_tot',
                'pay_tot_igst','pay_tot_cgst','pay_tot_sgst',
                'pay_itc_igst','pay_itc_cgst','pay_itc_sgst',
                'pay_csh_igst','pay_csh_cgst','pay_csh_sgst',
              ].map((k, idx) => {
                const dv = diffVal(k)
                return <td key={idx} className={diffCls(dv)}>{fmtDiff(dv)}</td>
              })}
            </tr>
          )}
        </tfoot>
      </table>
    </div>
  )
}

// ── GSTR-9 MOM table — Part-wise format matching reference Excel ──────────────
function GSTR9MOMTable({ files, analyticsById, fmtMode }) {
  const filesWithData = files.filter((f) => analyticsById[f.id])
  if (filesWithData.length === 0) return null

  const divisor = fmtMode === 'cr' ? 1e7 : fmtMode === 'l' ? 1e5 : 1
  const fv = (v) => {
    if (v == null) return '—'
    const n = Number(v); if (isNaN(n)) return '—'
    if (divisor === 1) return n.toLocaleString('en-IN', { maximumFractionDigits: 2 })
    return (n / divisor).toLocaleString('en-IN', { maximumFractionDigits: 2 })
  }

  const val = (d, pfx, sfx) => d[`${pfx}_${sfx}`] ?? null

  // Flat row definitions for Parts II & III.
  // noTaxable: CGST/SGST/IGST/Cess only (no Taxable Value column)
  // taxOnly:   Taxable Value only (no tax columns)
  const ROW_DEFS = [
    { _div: 'Part II — Section 4 · Outward Supplies (Tax Payable)' },
    { sr:'4A', desc:'B2C Supplies (Unregistered)',      pfx:'4A_B2C' },
    { sr:'4B', desc:'B2B Supplies (Registered)',         pfx:'4B_B2B' },
    { sr:'4C', desc:'Zero-Rated Exports (with tax)',     pfx:'4C_Export_WithTax' },
    { sr:'4D', desc:'SEZ Supplies (with tax)',            pfx:'4D_SEZ_WithTax' },
    { sr:'4E', desc:'Deemed Exports',                    pfx:'4E_DeemedExports' },
    { sr:'4F', desc:'Advances Received / Adjusted',      pfx:'4F_Advances' },
    { sr:'4G', desc:'Inward RCM Supplies',               pfx:'4G_RCM_Inward' },
    { sr:'4H', desc:'Sub-Total (A to G)',                pfx:'4H_SubTotal_AtoG',   isTotal:true },
    { sr:'4I', desc:'Credit Notes',                      pfx:'4I_CreditNotes' },
    { sr:'4J', desc:'Debit Notes',                       pfx:'4J_DebitNotes' },
    { sr:'4K', desc:'Amendments (+)',                    pfx:'4K_Amendments_Plus' },
    { sr:'4L', desc:'Amendments (−)',                    pfx:'4L_Amendments_Minus' },
    { sr:'4M', desc:'Sub-Total (I to L)',                pfx:'4M_SubTotal_ItoL',   isTotal:true },
    { sr:'4N', desc:'Net Tax Payable on Outward',        pfx:'4N_Net_TaxPayable',  isTotal:true },
    { _div: 'Part II — Section 5 · Non-Taxable Outward Supplies' },
    { sr:'5A', desc:'Exports without payment of tax',           pfx:'5A_Export_WithoutTax',   taxOnly:true },
    { sr:'5B', desc:'SEZ without payment of tax',               pfx:'5B_SEZ_WithoutTax',      taxOnly:true },
    { sr:'5C', desc:'RCM (recipient liable)',                    pfx:'5C_RCM_Recipient',       taxOnly:true },
    { sr:'5D', desc:'Exempted Supplies',                        pfx:'5D_Exempted',            taxOnly:true },
    { sr:'5E', desc:'Nil-Rated Supplies',                       pfx:'5E_NilRated',            taxOnly:true },
    { sr:'5F', desc:'Non-GST Supplies',                         pfx:'5F_NonGST',              taxOnly:true },
    { sr:'5G', desc:'Sub-Total (A to F)',                       pfx:'5G_SubTotal_AtoF',       taxOnly:true, isTotal:true },
    { sr:'5H', desc:'Credit Notes on A to F (−)',               pfx:'5H_CreditNotes',         taxOnly:true },
    { sr:'5I', desc:'Debit Notes on A to F (+)',                pfx:'5I_DebitNotes',          taxOnly:true },
    { sr:'5J', desc:'Amendments (+)',                            pfx:'5J_Amendments_Plus',     taxOnly:true },
    { sr:'5K', desc:'Amendments (−)',                            pfx:'5K_Amendments_Minus',    taxOnly:true },
    { sr:'5L', desc:'Sub-Total (H to K)',                       pfx:'5L_SubTotal_HtoK',       taxOnly:true, isTotal:true },
    { sr:'5M', desc:'Total Non-Taxable Turnover (G + L)',       pfx:'5M_Turnover_NonTaxable', taxOnly:true, isTotal:true },
    { sr:'5N', desc:'Total Turnover (4N + 5M − 4G)',           pfx:'5N_TotalTurnover',       isTotal:true },
    { _div: 'Part III — Section 6 · ITC Availed During FY' },
    { sr:'6A',  desc:'Total ITC as per GSTR-3B',                                         pfx:'6A_ITC_GSTR3B',         noTaxable:true },
    { sr:'6A1', desc:'ITC from preceding FY availed in Apr–Sep (excl. reclaim)',          pfx:'6A1_PrecedingFY_ITC',   noTaxable:true },
    { sr:'6A2', desc:'Net ITC for current FY (6A − 6A1)',                                pfx:'6A2_Net_ITC',           noTaxable:true },
    { sr:'6B',  desc:'Inputs (Registered)',                                               pfx:'6B_Inputs_Inputs',      noTaxable:true, type:'Inputs' },
    { sr:'6B',  desc:'Capital Goods (Registered)',                                        pfx:'6B_Inputs_CapGoods',    noTaxable:true, type:'Capital Goods' },
    { sr:'6B',  desc:'Input Services (Registered)',                                       pfx:'6B_Inputs_InputSvcs',   noTaxable:true, type:'Input Services' },
    { sr:'6E',  desc:'Import of Goods (Inputs)',                                          pfx:'6E_Import_Goods_Inputs',noTaxable:true },
    { sr:'6F',  desc:'Import of Services',                                                pfx:'6F_Import_Svcs',        noTaxable:true },
    { sr:'6G',  desc:'ISD Credit',                                                        pfx:'6G_ISD',                noTaxable:true },
    { sr:'6I',  desc:'Sub-Total ITC (B to H)',                                            pfx:'6I_SubTotal_BtoH',      noTaxable:true, isTotal:true },
    { sr:'6J',  desc:'Difference (6I − 6A)',                                              pfx:'6J_Difference_IminusA', noTaxable:true },
    { sr:'6O',  desc:'Total ITC Availed',                                                 pfx:'6O_TotalITC',           noTaxable:true, isTotal:true },
    { _div: 'Part III — Section 7 · ITC Reversed & Ineligible ITC' },
    { sr:'7A',  desc:'Rule 37 (non-payment > 180 days)',   pfx:'7A_Rule37',              noTaxable:true },
    { sr:'7A1', desc:'Rule 37A (CIRP)',                    pfx:'7A1_Rule37A',            noTaxable:true },
    { sr:'7A2', desc:'Rule 38 (inputs held in stock)',     pfx:'7A2_Rule38',             noTaxable:true },
    { sr:'7B',  desc:'Rule 39 (ISD reversal)',             pfx:'7B_Rule39',              noTaxable:true },
    { sr:'7C',  desc:'Rule 42 (common credit)',            pfx:'7C_Rule42',              noTaxable:true },
    { sr:'7D',  desc:'Rule 43 (capital goods)',            pfx:'7D_Rule43',              noTaxable:true },
    { sr:'7E',  desc:'Section 17(5) – Blocked Credits',   pfx:'7E_Sec17_5',             noTaxable:true },
    { sr:'7H1', desc:'Other Reversals',                   pfx:'7H1_OtherReversal',      noTaxable:true },
    { sr:'7I',  desc:'Total ITC Reversed',                 pfx:'7I_Total_ITC_Reversed',  noTaxable:true, isTotal:true },
    { sr:'7J',  desc:'Net ITC Utilizable',                 pfx:'7J_NetITC_Utilizable',   noTaxable:true, isTotal:true },
    { _div: 'Part III — Section 8 · Other ITC Related Information' },
    { sr:'8A',  desc:'ITC as per GSTR-2A (Eligible ITC only)',               pfx:'8A_GSTR2A_ITC',          noTaxable:true },
    { sr:'8B',  desc:'ITC as per sum of 6(B) and 6(H)',                      pfx:'8B_ITC_6B_6H',           noTaxable:true },
    { sr:'8C',  desc:'ITC on inward supplies (previous FY)',                  pfx:'8C_NextFY_ITC',          noTaxable:true },
    { sr:'8D',  desc:'Difference [A − (B + C)]',                             pfx:'8D_Difference',          noTaxable:true },
    { sr:'8E',  desc:'ITC available but not availed (out of D)',              pfx:'8E_Available_NotAvailed',noTaxable:true },
    { sr:'8F',  desc:'ITC available but ineligible (out of D)',               pfx:'8F_Available_Ineligible',noTaxable:true },
    { sr:'8G',  desc:'IGST paid on import of goods (incl. SEZ)',              pfx:'8G_IGST_Import_Paid',    noTaxable:true },
    { sr:'8H',  desc:'IGST credit availed on import (current FY, per 6E)',   pfx:'8H_IGST_Import_Availed', noTaxable:true },
    { sr:'8H1', desc:'IGST credit availed on import (next FY)',              pfx:'8H1_IGST_Import_NextFY', noTaxable:true },
    { sr:'8I',  desc:'Difference (G − H − H1)',                              pfx:'8I_Diff_GH',             noTaxable:true },
    { sr:'8J',  desc:'ITC on import available but not availed',              pfx:'8J_NotAvailed_Import',   noTaxable:true },
    { sr:'8K',  desc:'Total ITC to be lapsed in current FY (E + F + J)',     pfx:'8K_ITC_To_Lapse',        noTaxable:true, isTotal:true },
  ]

  // Part IV (Tax Paid) — different column structure
  const P9_ROWS = [
    { sr:'9A', desc:'IGST',       payK:'9A_IGST_Payable',     cashK:'9A_IGST_Cash',     cK:'9A_IGST_ITC_CGST', sK:'9A_IGST_ITC_SGST', iK:'9A_IGST_ITC_IGST', cessK:'9A_IGST_ITC_Cess' },
    { sr:'9B', desc:'CGST',       payK:'9B_CGST_Payable',     cashK:'9B_CGST_Cash',     cK:'9B_CGST_ITC_CGST', sK:null,               iK:'9B_CGST_ITC_IGST', cessK:null },
    { sr:'9C', desc:'SGST/UTGST', payK:'9C_SGST_Payable',     cashK:'9C_SGST_Cash',     cK:null,               sK:'9C_SGST_ITC_SGST', iK:'9C_SGST_ITC_IGST', cessK:null },
    { sr:'9D', desc:'Cess',       payK:'9D_Cess_Payable',     cashK:'9D_Cess_Cash',     cK:null,               sK:null,               iK:null,               cessK:'9D_Cess_ITC_Cess' },
    { sr:'9E', desc:'Interest',   payK:'9E_Interest_Payable',  cashK:'9E_Interest_Cash', cK:null,               sK:null,               iK:null,               cessK:null },
    { sr:'9F', desc:'Late Fee',   payK:'9F_LateFee_Payable',   cashK:'9F_LateFee_Cash',  cK:null,               sK:null,               iK:null,               cessK:null },
    { sr:'9G', desc:'Penalty',    payK:'9G_Penalty_Payable',   cashK:'9G_Penalty_Cash',  cK:null,               sK:null,               iK:null,               cessK:null },
    { sr:'9H', desc:'Other',      payK:'9H_Other_Payable',     cashK:'9H_Other_Cash',    cK:null,               sK:null,               iK:null,               cessK:null },
  ]

  const n = filesWithData.length

  const dataFor = (d, def) => {
    if (def.noTaxable) return [null, val(d,def.pfx,'CGST'), val(d,def.pfx,'SGST'), val(d,def.pfx,'IGST'), val(d,def.pfx,'Cess')]
    if (def.taxOnly)   return [val(d,def.pfx,'TaxableValue'), null, null, null, null]
    return [val(d,def.pfx,'TaxableValue'), val(d,def.pfx,'CGST'), val(d,def.pfx,'SGST'), val(d,def.pfx,'IGST'), val(d,def.pfx,'Cess')]
  }

  const thG  = 'px-2 py-1.5 text-center text-[9px] font-bold uppercase tracking-wider border-b border-slate-700 whitespace-nowrap'
  const thS  = 'px-2 py-1.5 text-right text-[9px] font-semibold text-slate-500 whitespace-nowrap'
  const tdD  = 'px-2 py-1.5 text-right font-mono text-[10px] text-slate-300 whitespace-nowrap'
  const tdT  = 'px-2 py-1.5 text-right font-mono text-[10px] font-bold text-white whitespace-nowrap'
  const divTd = 'px-3 py-1.5 text-[9px] font-bold uppercase tracking-wider text-slate-300 bg-slate-800/70'

  return (
    <div className="space-y-5">
      {/* ── Parts II & III ── */}
      <div className="overflow-x-auto rounded-xl border border-slate-800">
        <table className="text-xs border-collapse" style={{ minWidth: `${800 + n * 350}px` }}>
          <thead>
            <tr className="bg-slate-900 border-b border-slate-700">
              <th rowSpan={2} className="sticky left-0 z-10 bg-slate-900 px-2 py-2 text-left text-[9px] font-bold text-slate-400 uppercase border-b border-r border-slate-700 w-8 align-bottom">Sr</th>
              <th rowSpan={2} className="px-2 py-2 text-left text-[9px] font-bold text-slate-400 uppercase border-b border-slate-700 min-w-[220px] align-bottom">Description</th>
              <th rowSpan={2} className="px-2 py-2 text-left text-[9px] font-bold text-slate-400 uppercase border-b border-slate-700 w-24 align-bottom">Type</th>
              {filesWithData.map((f, fi) => (
                <th key={fi} colSpan={5} className={`${thG} border-l-2 border-slate-700 text-amber-300`}>
                  {f.period || f.name || `Year ${fi + 1}`}
                </th>
              ))}
            </tr>
            <tr className="bg-slate-900/80 border-b border-slate-800">
              {filesWithData.map((_, fi) => (
                <React.Fragment key={fi}>
                  <th className={`${thS} border-l-2 border-slate-700`}>Taxable Value</th>
                  <th className={thS}>Central Tax</th>
                  <th className={thS}>State/UT Tax</th>
                  <th className={thS}>Integrated Tax</th>
                  <th className={thS}>Cess</th>
                </React.Fragment>
              ))}
            </tr>
          </thead>
          <tbody>
            {ROW_DEFS.map((def, ri) => {
              if (def._div) {
                return (
                  <tr key={ri}>
                    <td colSpan={3 + n * 5} className={divTd}>{def._div}</td>
                  </tr>
                )
              }
              return (
                <tr key={ri} className={`border-t border-slate-800/40 ${def.isTotal ? 'bg-slate-800/20' : 'hover:bg-slate-800/10'}`}>
                  <td className="sticky left-0 z-10 bg-slate-950 px-2 py-1.5 text-slate-500 font-mono text-[10px] border-r border-slate-800 whitespace-nowrap">{def.sr}</td>
                  <td className="px-2 py-1.5 text-slate-300 text-[10px] leading-tight">{def.desc}</td>
                  <td className="px-2 py-1.5 text-slate-500 text-[10px] italic whitespace-nowrap">{def.type || ''}</td>
                  {filesWithData.map((f, fi) => {
                    const d    = analyticsById[f.id]?.extracted_data || {}
                    const vals = dataFor(d, def)
                    return (
                      <React.Fragment key={fi}>
                        {vals.map((v, vi) => (
                          <td key={vi} className={`${def.isTotal ? tdT : tdD} ${vi === 0 ? 'border-l-2 border-slate-700' : ''}`}>
                            {fv(v)}
                          </td>
                        ))}
                      </React.Fragment>
                    )
                  })}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {/* ── Part IV — Tax Paid (different column structure) ── */}
      <div>
        <div className="flex items-center gap-2 mb-2">
          <span className="px-2 py-0.5 text-[9px] font-bold bg-rose-600/20 text-rose-300 border border-rose-600/30 rounded uppercase tracking-wider">Part IV</span>
          <span className="text-[11px] text-slate-500">Details of Tax Paid as Declared in Returns (Section 9)</span>
        </div>
        <div className="overflow-x-auto rounded-xl border border-slate-800">
          <table className="text-xs border-collapse" style={{ minWidth: `${500 + n * 384}px` }}>
            <thead>
              <tr className="bg-slate-900 border-b border-slate-700">
                <th rowSpan={2} className="px-2 py-2 text-left text-[9px] font-bold text-slate-400 uppercase border-b border-r border-slate-700 w-8 align-bottom">Sr</th>
                <th rowSpan={2} className="px-2 py-2 text-left text-[9px] font-bold text-slate-400 uppercase border-b border-slate-700 min-w-[110px] align-bottom">Description</th>
                {filesWithData.map((f, fi) => (
                  <th key={fi} colSpan={6} className={`${thG} border-l-2 border-slate-700 text-rose-300`}>
                    {f.period || f.name || `Year ${fi + 1}`}
                  </th>
                ))}
              </tr>
              <tr className="bg-slate-900/80 border-b border-slate-800">
                {filesWithData.map((_, fi) => (
                  <React.Fragment key={fi}>
                    <th className={`${thS} border-l-2 border-slate-700`}>Tax Payable</th>
                    <th className={thS}>Cash Paid</th>
                    <th className={thS}>ITC – CGST</th>
                    <th className={thS}>ITC – SGST</th>
                    <th className={thS}>ITC – IGST</th>
                    <th className={thS}>ITC – Cess</th>
                  </React.Fragment>
                ))}
              </tr>
            </thead>
            <tbody>
              {P9_ROWS.map((def, ri) => (
                <tr key={ri} className="border-t border-slate-800/40 hover:bg-slate-800/10">
                  <td className="px-2 py-1.5 text-slate-500 font-mono text-[10px] border-r border-slate-800">{def.sr}</td>
                  <td className="px-2 py-1.5 text-slate-300 text-[10px]">{def.desc}</td>
                  {filesWithData.map((f, fi) => {
                    const d = analyticsById[f.id]?.extracted_data || {}
                    return (
                      <React.Fragment key={fi}>
                        <td className={`${tdD} border-l-2 border-slate-700`}>{fv(d[def.payK])}</td>
                        <td className={tdD}>{fv(d[def.cashK])}</td>
                        <td className={tdD}>{fv(def.cK    ? d[def.cK]    : null)}</td>
                        <td className={tdD}>{fv(def.sK    ? d[def.sK]    : null)}</td>
                        <td className={tdD}>{fv(def.iK    ? d[def.iK]    : null)}</td>
                        <td className={tdD}>{fv(def.cessK ? d[def.cessK] : null)}</td>
                      </React.Fragment>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* ── Part V Table 14 — Differential Tax Paid ── */}
      <div>
        <div className="flex items-center gap-2 mb-2">
          <span className="px-2 py-0.5 text-[9px] font-bold bg-violet-600/20 text-violet-300 border border-violet-600/30 rounded uppercase tracking-wider">Part V · Table 14</span>
          <span className="text-[11px] text-slate-500">Differential Tax Paid on Account of Declarations in Table 10 &amp; 11</span>
        </div>
        <div className="overflow-x-auto rounded-xl border border-slate-800">
          <table className="text-xs border-collapse" style={{ minWidth: `${400 + n * 192}px` }}>
            <thead>
              <tr className="bg-slate-900 border-b border-slate-700">
                <th rowSpan={2} className="px-2 py-2 text-left text-[9px] font-bold text-slate-400 uppercase border-b border-r border-slate-700 w-8 align-bottom">Sr</th>
                <th rowSpan={2} className="px-2 py-2 text-left text-[9px] font-bold text-slate-400 uppercase border-b border-slate-700 min-w-[110px] align-bottom">Tax Type</th>
                {filesWithData.map((f, fi) => (
                  <th key={fi} colSpan={2} className={`${thG} border-l-2 border-slate-700 text-violet-300`}>
                    {f.period || f.name || `Year ${fi + 1}`}
                  </th>
                ))}
              </tr>
              <tr className="bg-slate-900/80 border-b border-slate-800">
                {filesWithData.map((_, fi) => (
                  <React.Fragment key={fi}>
                    <th className={`${thS} border-l-2 border-slate-700`}>Tax Payable</th>
                    <th className={thS}>Cash Paid</th>
                  </React.Fragment>
                ))}
              </tr>
            </thead>
            <tbody>
              {[
                { sr:'14A', desc:'Integrated Tax',  pK:'14A_IGST_Payable',    cK:'14A_IGST_Cash' },
                { sr:'14B', desc:'Central Tax',     pK:'14B_CGST_Payable',    cK:'14B_CGST_Cash' },
                { sr:'14C', desc:'State / UT Tax',  pK:'14C_SGST_Payable',    cK:'14C_SGST_Cash' },
                { sr:'14D', desc:'Cess',             pK:'14D_Cess_Payable',    cK:'14D_Cess_Cash' },
                { sr:'14E', desc:'Interest',         pK:'14E_Interest_Payable',cK:'14E_Interest_Cash' },
              ].map((def, ri) => (
                <tr key={ri} className="border-t border-slate-800/40 hover:bg-slate-800/10">
                  <td className="px-2 py-1.5 text-slate-500 font-mono text-[10px] border-r border-slate-800">{def.sr}</td>
                  <td className="px-2 py-1.5 text-slate-300 text-[10px]">{def.desc}</td>
                  {filesWithData.map((f, fi) => {
                    const d = analyticsById[f.id]?.extracted_data || {}
                    return (
                      <React.Fragment key={fi}>
                        <td className={`${tdD} border-l-2 border-slate-700`}>{fv(d[def.pK])}</td>
                        <td className={tdD}>{fv(d[def.cK])}</td>
                      </React.Fragment>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* ── Part VI — Other Information ── */}
      <div className="space-y-4">
        <div className="flex items-center gap-2">
          <span className="px-2 py-0.5 text-[9px] font-bold bg-teal-600/20 text-teal-300 border border-teal-600/30 rounded uppercase tracking-wider">Part VI</span>
          <span className="text-[11px] text-slate-500">Other Information</span>
        </div>

        {/* Table 15 */}
        <div>
          <div className="text-[9px] font-semibold text-slate-500 uppercase tracking-wider mb-1.5 px-1">15 · Demands and Refunds</div>
          <div className="overflow-x-auto rounded-xl border border-slate-800">
            <table className="text-xs border-collapse" style={{ minWidth: `${400 + n * 280}px` }}>
              <thead>
                <tr className="bg-slate-900 border-b border-slate-700">
                  <th rowSpan={2} className="px-2 py-2 text-left text-[9px] font-bold text-slate-400 uppercase border-b border-r border-slate-700 w-8 align-bottom">Sr</th>
                  <th rowSpan={2} className="px-2 py-2 text-left text-[9px] font-bold text-slate-400 uppercase border-b border-slate-700 min-w-[160px] align-bottom">Particulars</th>
                  {filesWithData.map((f, fi) => (
                    <th key={fi} colSpan={4} className={`${thG} border-l-2 border-slate-700 text-teal-300`}>
                      {f.period || f.name || `Year ${fi + 1}`}
                    </th>
                  ))}
                </tr>
                <tr className="bg-slate-900/80 border-b border-slate-800">
                  {filesWithData.map((_, fi) => (
                    <React.Fragment key={fi}>
                      <th className={`${thS} border-l-2 border-slate-700`}>CGST</th>
                      <th className={thS}>SGST</th>
                      <th className={thS}>IGST</th>
                      <th className={thS}>Cess</th>
                    </React.Fragment>
                  ))}
                </tr>
              </thead>
              <tbody>
                {[
                  { sr:'15A', desc:'Demand of taxes',                        pfx:'15A_Tax_Demands' },
                  { sr:'15B', desc:'Taxes paid in full against demands',     pfx:'15B_Tax_Demands_Paid' },
                  { sr:'15C', desc:'Taxes paid partially against demands',   pfx:'15C_Tax_Demands_Partial' },
                  { sr:'15D', desc:'Taxes & interest refund claimed',        pfx:'15D_Refunds_Claimed' },
                  { sr:'15E', desc:'Taxes & interest refund sanctioned',     pfx:'15E_Refunds_Sanctioned' },
                  { sr:'15F', desc:'Taxes & interest refund rejected',       pfx:'15F_Refunds_Rejected' },
                  { sr:'15G', desc:'Taxes & interest refund pending',        pfx:'15G_Refunds_Pending' },
                ].map((def, ri) => (
                  <tr key={ri} className="border-t border-slate-800/40 hover:bg-slate-800/10">
                    <td className="px-2 py-1.5 text-slate-500 font-mono text-[10px] border-r border-slate-800">{def.sr}</td>
                    <td className="px-2 py-1.5 text-slate-300 text-[10px]">{def.desc}</td>
                    {filesWithData.map((f, fi) => {
                      const d = analyticsById[f.id]?.extracted_data || {}
                      return (
                        <React.Fragment key={fi}>
                          <td className={`${tdD} border-l-2 border-slate-700`}>{fv(d[`${def.pfx}_CGST`])}</td>
                          <td className={tdD}>{fv(d[`${def.pfx}_SGST`])}</td>
                          <td className={tdD}>{fv(d[`${def.pfx}_IGST`])}</td>
                          <td className={tdD}>{fv(d[`${def.pfx}_Cess`])}</td>
                        </React.Fragment>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Table 16 */}
        <div>
          <div className="text-[9px] font-semibold text-slate-500 uppercase tracking-wider mb-1.5 px-1">16 · Composition Taxpayers / Job Work / Goods on Approval</div>
          <div className="overflow-x-auto rounded-xl border border-slate-800">
            <table className="text-xs border-collapse" style={{ minWidth: `${400 + n * 192}px` }}>
              <thead>
                <tr className="bg-slate-900 border-b border-slate-700">
                  <th rowSpan={2} className="px-2 py-2 text-left text-[9px] font-bold text-slate-400 uppercase border-b border-r border-slate-700 w-8 align-bottom">Sr</th>
                  <th rowSpan={2} className="px-2 py-2 text-left text-[9px] font-bold text-slate-400 uppercase border-b border-slate-700 min-w-[200px] align-bottom">Particulars</th>
                  {filesWithData.map((f, fi) => (
                    <th key={fi} colSpan={2} className={`${thG} border-l-2 border-slate-700 text-teal-300`}>
                      {f.period || f.name || `Year ${fi + 1}`}
                    </th>
                  ))}
                </tr>
                <tr className="bg-slate-900/80 border-b border-slate-800">
                  {filesWithData.map((_, fi) => (
                    <React.Fragment key={fi}>
                      <th className={`${thS} border-l-2 border-slate-700`}>Taxable Value</th>
                      <th className={thS}>Tax</th>
                    </React.Fragment>
                  ))}
                </tr>
              </thead>
              <tbody>
                {[
                  { sr:'16A', desc:'Supplies from composition taxpayers',    pfx:'16A_Composition_Inward' },
                  { sr:'16B', desc:'Deemed supply u/s 143 (job work)',       pfx:'16B_JobWork_DeemedSupply' },
                  { sr:'16C', desc:'Goods sent on approval basis (not returned)', pfx:'16C_GoodsOnApproval' },
                ].map((def, ri) => (
                  <tr key={ri} className="border-t border-slate-800/40 hover:bg-slate-800/10">
                    <td className="px-2 py-1.5 text-slate-500 font-mono text-[10px] border-r border-slate-800">{def.sr}</td>
                    <td className="px-2 py-1.5 text-slate-300 text-[10px]">{def.desc}</td>
                    {filesWithData.map((f, fi) => {
                      const d = analyticsById[f.id]?.extracted_data || {}
                      return (
                        <React.Fragment key={fi}>
                          <td className={`${tdD} border-l-2 border-slate-700`}>{fv(d[`${def.pfx}_TaxableValue`])}</td>
                          <td className={tdD}>{fv(d[`${def.pfx}_Tax`])}</td>
                        </React.Fragment>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Table 19 */}
        <div>
          <div className="text-[9px] font-semibold text-slate-500 uppercase tracking-wider mb-1.5 px-1">19 · Late Fee Payable and Paid</div>
          <div className="overflow-x-auto rounded-xl border border-slate-800">
            <table className="text-xs border-collapse" style={{ minWidth: `${400 + n * 192}px` }}>
              <thead>
                <tr className="bg-slate-900 border-b border-slate-700">
                  <th rowSpan={2} className="px-2 py-2 text-left text-[9px] font-bold text-slate-400 uppercase border-b border-r border-slate-700 w-8 align-bottom">Sr</th>
                  <th rowSpan={2} className="px-2 py-2 text-left text-[9px] font-bold text-slate-400 uppercase border-b border-slate-700 min-w-[110px] align-bottom">Tax Type</th>
                  {filesWithData.map((f, fi) => (
                    <th key={fi} colSpan={2} className={`${thG} border-l-2 border-slate-700 text-teal-300`}>
                      {f.period || f.name || `Year ${fi + 1}`}
                    </th>
                  ))}
                </tr>
                <tr className="bg-slate-900/80 border-b border-slate-800">
                  {filesWithData.map((_, fi) => (
                    <React.Fragment key={fi}>
                      <th className={`${thS} border-l-2 border-slate-700`}>Payable</th>
                      <th className={thS}>Paid</th>
                    </React.Fragment>
                  ))}
                </tr>
              </thead>
              <tbody>
                {[
                  { sr:'19A', desc:'Central Tax',    pK:'19A_CentralTax_LateFee_Payable', cK:'19A_CentralTax_LateFee_Paid' },
                  { sr:'19B', desc:'State / UT Tax', pK:'19B_StateTax_LateFee_Payable',   cK:'19B_StateTax_LateFee_Paid' },
                ].map((def, ri) => (
                  <tr key={ri} className="border-t border-slate-800/40 hover:bg-slate-800/10">
                    <td className="px-2 py-1.5 text-slate-500 font-mono text-[10px] border-r border-slate-800">{def.sr}</td>
                    <td className="px-2 py-1.5 text-slate-300 text-[10px]">{def.desc}</td>
                    {filesWithData.map((f, fi) => {
                      const d = analyticsById[f.id]?.extracted_data || {}
                      return (
                        <React.Fragment key={fi}>
                          <td className={`${tdD} border-l-2 border-slate-700`}>{fv(d[def.pK])}</td>
                          <td className={tdD}>{fv(d[def.cK])}</td>
                        </React.Fragment>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── MOM Dashboard shell ───────────────────────────────────────────────────────
// ── Financial-Year month sort ─────────────────────────────────────────────────
// Handles both full ("January") and abbreviated ("Jan") month names
// FY order: Apr=0, May=1 … Dec=8, Jan=9, Feb=10, Mar=11
const _FY_POS = {
  april:0, may:1, june:2, july:3, august:4, september:5,
  october:6, november:7, december:8, january:9, february:10, march:11,
  apr:0, jun:2, jul:3, aug:4, sep:5,
  oct:6, nov:7, dec:8, jan:9, feb:10, mar:11,
}
function _fySortKey(period) {
  if (!period) return [9999, 99]
  const parts = period.trim().split(/\s+/)
  if (parts.length < 2) return [9999, 99]
  const mon  = parts[0].toLowerCase()
  const year = parseInt(parts[1]) || 0
  const pos  = _FY_POS[mon] ?? 99
  // Jan/Feb/Mar belong to the FY that started the previous April
  const fyStart = pos >= 9 ? year - 1 : year
  return [fyStart, pos]
}
function sortByFY(files) {
  return [...files].sort((a, b) => {
    const [aY, aP] = _fySortKey(a.period)
    const [bY, bP] = _fySortKey(b.period)
    return aY !== bY ? aY - bY : aP - bP
  })
}

function MOMDashboard({ uploadedFiles, analyticsById }) {
  const [fmtMode, setFmtMode] = useState('raw')
  const { annualFileId, setAnnualFileId, annualFileId3B, setAnnualFileId3B } = useApp()

  const allWithData = uploadedFiles.filter((f) => analyticsById[f.id])
  const gstr1Files  = sortByFY(allWithData.filter((f) => f.gst_type === 'GSTR-1' && f.id !== annualFileId))
  const gstr3bFiles = sortByFY(allWithData.filter((f) => f.gst_type === 'GSTR-3B' && f.id !== annualFileId3B))
  const gstr9Files  = sortByFY(allWithData.filter((f) => f.gst_type === 'GSTR-9'))
  const has1  = gstr1Files.length  > 0
  const has3B = gstr3bFiles.length > 0
  const has9  = gstr9Files.length  > 0

  const annualFile   = annualFileId   ? uploadedFiles.find((f) => f.id === annualFileId)   : null
  const annualExt    = annualFileId   ? (analyticsById[annualFileId]?.extracted_data   || null) : null
  const annualFile3B = annualFileId3B ? uploadedFiles.find((f) => f.id === annualFileId3B) : null
  const annualExt3B  = annualFileId3B ? (analyticsById[annualFileId3B]?.extracted_data || null) : null

  if (!has1 && !has3B && !has9) {
    return (
      <div className="flex flex-col items-center justify-center h-64 text-slate-700">
        <Calendar className="w-12 h-12 mb-3 opacity-30" />
        <p className="text-sm">Upload multiple GST PDFs to see month-over-month analysis</p>
      </div>
    )
  }

  const totalFiles = allWithData.length
  const missingCount = uploadedFiles.length - allWithData.length

  return (
    <div className="space-y-4">
      {/* Controls */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <h2 className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">
          Month-over-Month · {totalFiles} file(s)
        </h2>
        <div className="flex items-center gap-2 flex-wrap">
          <div className="flex gap-1 bg-slate-900 border border-slate-800 rounded-lg p-0.5">
            {[['raw','Raw'],['l','Lakhs'],['cr','Crores']].map(([m, label]) => (
              <button key={m} onClick={() => setFmtMode(m)}
                className={`px-2.5 py-1 text-[11px] font-medium rounded-md transition-all ${
                  fmtMode === m ? 'bg-blue-600 text-white' : 'text-slate-500 hover:text-slate-300'
                }`}>
                {label}
              </button>
            ))}
          </div>
          {has1 && (
            <div className="flex items-center gap-1.5">
              <span className="text-[10px] text-slate-500 whitespace-nowrap">Annual Ref:</span>
              <select
                value={annualFileId || ''}
                onChange={(e) => setAnnualFileId(e.target.value || null)}
                className="text-[10px] bg-slate-900 border border-slate-700 text-slate-300 rounded-md px-2 py-1 focus:outline-none focus:border-amber-500/60 cursor-pointer"
              >
                <option value="">— None —</option>
                {uploadedFiles.filter((f) => analyticsById[f.id] && f.gst_type === 'GSTR-1').map((f) => (
                  <option key={f.id} value={f.id}>
                    {f.name.length > 28 ? f.name.slice(0,28)+'…' : f.name}
                    {f.period ? ` (${f.period})` : ''}
                  </option>
                ))}
              </select>
            </div>
          )}
          {has1 && (
            <button
              onClick={() => exportMOMExcel(fmtMode, annualFileId)}
              className="flex items-center gap-1.5 px-2.5 py-1 text-[11px] font-medium rounded-lg
                         bg-emerald-600/15 border border-emerald-600/30 text-emerald-400
                         hover:bg-emerald-600/25 transition-colors"
            >
              <FileSpreadsheet className="w-3 h-3" /> Export GSTR-1
            </button>
          )}
          {has3B && (
            <div className="flex items-center gap-1.5">
              <span className="text-[10px] text-slate-500 whitespace-nowrap">3B Annual Ref:</span>
              <select
                value={annualFileId3B || ''}
                onChange={(e) => setAnnualFileId3B(e.target.value || null)}
                className="text-[10px] bg-slate-900 border border-slate-700 text-slate-300 rounded-md px-2 py-1 focus:outline-none focus:border-teal-500/60 cursor-pointer"
              >
                <option value="">— None —</option>
                {uploadedFiles.filter((f) => analyticsById[f.id] && f.gst_type === 'GSTR-3B').map((f) => (
                  <option key={f.id} value={f.id}>
                    {f.name.length > 28 ? f.name.slice(0,28)+'…' : f.name}
                    {f.period ? ` (${f.period})` : ''}
                  </option>
                ))}
              </select>
            </div>
          )}
          {has3B && (
            <button
              onClick={() => exportMOM3BExcel(fmtMode, annualFileId3B)}
              className="flex items-center gap-1.5 px-2.5 py-1 text-[11px] font-medium rounded-lg
                         bg-teal-600/15 border border-teal-600/30 text-teal-400
                         hover:bg-teal-600/25 transition-colors"
            >
              <FileSpreadsheet className="w-3 h-3" /> Export GSTR-3B
            </button>
          )}
          {has9 && (
            <button
              onClick={() => exportMOM9Excel(fmtMode)}
              className="flex items-center gap-1.5 px-2.5 py-1 text-[11px] font-medium rounded-lg
                         bg-amber-600/15 border border-amber-600/30 text-amber-400
                         hover:bg-amber-600/25 transition-colors"
            >
              <FileSpreadsheet className="w-3 h-3" /> Export GSTR-9
            </button>
          )}
        </div>
      </div>

      {/* Amber anomaly legend */}
      <div className="flex items-center gap-1.5 text-[10px] text-amber-500/80">
        <span className="inline-block w-3 h-3 rounded-sm bg-amber-500/10 ring-1 ring-amber-500/35 flex-shrink-0" />
        Cells with ≥50% change from previous period are highlighted
      </div>

      {/* GSTR-1 section */}
      {has1 && (
        <section>
          <div className="flex items-center gap-2 mb-2">
            <span className="px-2.5 py-1 text-[10px] font-bold bg-indigo-600/20 text-indigo-300 border border-indigo-600/30 rounded-lg uppercase tracking-wider">GSTR-1</span>
            <span className="text-[11px] text-slate-500">Outward Supplies · Month-over-Month</span>
            <span className="text-[10px] text-slate-600">{gstr1Files.length} month(s)</span>
          </div>
          <GSTR1Table
            files={gstr1Files}
            analyticsById={analyticsById}
            fmtMode={fmtMode}
            annualFileId={annualFileId}
            annualFile={annualFile}
            annualExt={annualExt}
          />
        </section>
      )}

      {/* GSTR-3B section */}
      {has3B && (
        <section className={has1 ? 'mt-10' : ''}>
          <div className="flex items-center gap-2 mb-2">
            <span className="px-2.5 py-1 text-[10px] font-bold bg-emerald-600/20 text-emerald-300 border border-emerald-600/30 rounded-lg uppercase tracking-wider">GSTR-3B</span>
            <span className="text-[11px] text-slate-500">Summary Return · Month-over-Month</span>
            <span className="text-[10px] text-slate-600">{gstr3bFiles.length} month(s)</span>
          </div>
          <GSTR3BTable
            files={gstr3bFiles}
            analyticsById={analyticsById}
            fmtMode={fmtMode}
            annualFileId3B={annualFileId3B}
            annualFile3B={annualFile3B}
            annualExt3B={annualExt3B}
          />
        </section>
      )}

      {/* GSTR-9 section */}
      {has9 && (
        <section className={(has1 || has3B) ? 'mt-10' : ''}>
          <div className="flex items-center gap-2 mb-3">
            <span className="px-2.5 py-1 text-[10px] font-bold bg-amber-600/20 text-amber-300 border border-amber-600/30 rounded-lg uppercase tracking-wider">GSTR-9</span>
            <span className="text-[11px] text-slate-500">Annual Return · Part-wise Breakdown</span>
            <span className="text-[10px] text-slate-600">{gstr9Files.length} year(s)</span>
          </div>
          <GSTR9MOMTable
            files={gstr9Files}
            analyticsById={analyticsById}
            fmtMode={fmtMode}
          />
        </section>
      )}

      {missingCount > 0 && (
        <div className="flex items-center gap-2 px-3 py-2 bg-amber-500/10 border border-amber-500/20 rounded-lg">
          <AlertCircle className="w-3.5 h-3.5 text-amber-400 flex-shrink-0" />
          <p className="text-[11px] text-amber-400">
            {missingCount} file(s) still processing or have no extractable data.
          </p>
        </div>
      )}
    </div>
  )
}

// ── Main export ───────────────────────────────────────────────────────────────

/**
 * showDashboard(mode) — single entry point controlling what the center renders.
 * mode = "kpi"  → KPI cards + charts for the active file
 * mode = "mom"  → Month-over-Month table across all uploaded files
 */
export default function MainDashboard() {
  const {
    analytics,
    activeFile,
    uploadedFiles,
    analyticsById,
    currentMode,
    setCurrentMode,
  } = useApp()

  // ── Debug logging (mandatory) ─────────────────────────────────────────────
  useEffect(() => {
    console.log('[GST] dashboard_loaded:', {
      mode_detected: currentMode,
      files_count:   uploadedFiles.length,
      active_file:   activeFile?.name ?? null,
    })
  }, [currentMode, uploadedFiles.length, activeFile])

  // showDashboard: single function controlling rendering
  function showDashboard(mode) {
    console.log('[GST] toggle_clicked:', mode)
    setCurrentMode(mode)
  }

  return (
    <div className="flex flex-col h-full bg-slate-950">

      {/* ── Top bar: title + KPI/MOM toggle + upload ──────────────────────── */}
      <div className="flex items-center justify-between px-6 py-3 border-b border-slate-800/60 flex-shrink-0">

        {/* Left: title */}
        <div className="flex items-center gap-2.5">
          <TrendingUp className="w-4 h-4 text-blue-400 flex-shrink-0" />
          <span className="text-sm font-semibold text-white">
            {currentMode === 'kpi' ? 'KPI Dashboard'
              : currentMode === 'mom' ? 'Month-over-Month'
              : 'GSTR-2B Compiler'}
          </span>
          {activeFile && currentMode === 'kpi' && (
            <span className="text-xs text-slate-500 truncate">
              {activeFile.gst_type}
              {activeFile.period ? ` · ${activeFile.period}` : ''}
            </span>
          )}
          {currentMode === 'mom' && (
            <span className="text-xs text-slate-500">
              {uploadedFiles.length} file(s)
            </span>
          )}
        </div>

        {/* Right: KPI/MOM toggle + upload */}
        <div className="flex items-center gap-3">

          {/* [KPI] [MOM] [2B] toggle — top right, always visible */}
          <div
            className="flex items-center bg-slate-900 border border-slate-800 rounded-lg p-0.5"
            title="Toggle dashboard view"
          >
            {[['kpi','KPI'],['mom','MOM'],['2b','2B']].map(([m, label]) => (
              <button
                key={m}
                onClick={() => showDashboard(m)}
                className={`px-3 py-1.5 text-xs font-semibold rounded-md transition-all ${
                  currentMode === m
                    ? m === '2b'
                      ? 'bg-violet-600 text-white shadow-sm'
                      : 'bg-blue-600 text-white shadow-sm'
                    : 'text-slate-500 hover:text-slate-300'
                }`}
              >
                {label}
              </button>
            ))}
          </div>

          {/* Upload another file — hidden in 2B mode (panel has its own upload) */}
          {currentMode !== '2b' && <FileUpload compact />}
        </div>
      </div>

      {/* ── Dashboard content (scrollable) ────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto px-6 py-5">
        {currentMode === 'kpi' ? (
          <KPIDashboard
            analytics={analytics}
            activeFile={activeFile}
          />
        ) : currentMode === '2b' ? (
          <GSTR2BCompiler />
        ) : (
          <MOMDashboard
            uploadedFiles={uploadedFiles}
            analyticsById={analyticsById}
          />
        )}
      </div>
    </div>
  )
}
