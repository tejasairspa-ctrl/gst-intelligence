/**
 * GSTR9Panel — Analytics panel for GSTR-9 (Annual Return) and GSTR-9C (Reconciliation Statement).
 * Shows Summary KPIs, ratios, and insights only.
 * Part-wise breakdown has been moved to MOM view (MainDashboard → GSTR9MOMTable).
 */
import React from 'react'
import {
  BookOpen, Scale, Lightbulb, AlertTriangle,
  CheckCircle, ChevronDown, ChevronRight,
} from 'lucide-react'
import { KPIGrid } from './KPICard'
import { useApp } from '../context/AppContext'

// ── Number formatter ──────────────────────────────────────────────────────────
const fmtINR = (v) => {
  if (v === null || v === undefined) return '—'
  const n = Number(v)
  if (isNaN(n)) return '—'
  if (n === 0) return '0'
  return n.toLocaleString('en-IN', { maximumFractionDigits: 2 })
}

// ── Part-wise collapsible section ─────────────────────────────────────────────
function PartSection({ title, rows, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen)
  const hasData = rows.some((r) => r.values.some((v) => v !== null && v !== undefined))
  if (!hasData) return null

  return (
    <div className="mb-3">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center gap-1.5 py-1 text-left group"
      >
        {open
          ? <ChevronDown className="w-3 h-3 text-slate-500 flex-shrink-0" />
          : <ChevronRight className="w-3 h-3 text-slate-500 flex-shrink-0" />
        }
        <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider group-hover:text-slate-300 transition-colors">
          {title}
        </span>
      </button>

      {open && (
        <div className="mt-1 rounded-lg overflow-hidden border border-slate-800/60">
          <table className="w-full text-[9px]">
            <thead>
              <tr className="bg-slate-900/80 text-slate-500">
                <th className="text-left px-2 py-1 font-medium w-6">Sl.</th>
                <th className="text-left px-2 py-1 font-medium">Description</th>
                {rows[0]?.headers?.map((h) => (
                  <th key={h} className="text-right px-2 py-1 font-medium whitespace-nowrap">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr
                  key={i}
                  className={`border-t border-slate-800/40 ${
                    row.isTotal ? 'bg-slate-800/30 font-semibold' : 'hover:bg-slate-900/40'
                  }`}
                >
                  <td className="px-2 py-1 text-slate-600 font-mono">{row.label}</td>
                  <td className="px-2 py-1 text-slate-400 leading-tight">{row.desc}</td>
                  {row.values.map((v, j) => (
                    <td
                      key={j}
                      className={`px-2 py-1 text-right font-mono whitespace-nowrap ${
                        row.isTotal ? 'text-white' : 'text-slate-300'
                      } ${v !== null && v !== undefined && Number(v) < 0 ? 'text-amber-400' : ''}`}
                    >
                      {fmtINR(v)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ── Insight item ──────────────────────────────────────────────────────────────
function InsightItem({ text }) {
  return (
    <div className="flex gap-2 items-start">
      <Lightbulb className="w-3 h-3 text-amber-400 flex-shrink-0 mt-0.5" />
      <p className="text-[10px] text-slate-400 leading-relaxed">{text}</p>
    </div>
  )
}

// ── GSTR-9C reconciliation diff card ─────────────────────────────────────────
function Recon9CSummary({ data }) {
  const turnoverDiff = data.turnover_difference
  const itcDiff      = data.itc_difference
  const hasIssues    =
    (turnoverDiff != null && Math.abs(turnoverDiff) > 0) ||
    (itcDiff      != null && Math.abs(itcDiff)      > 0)

  return (
    <div
      className={`rounded-lg border px-3 py-2 ${
        hasIssues
          ? 'bg-amber-500/8 border-amber-500/25'
          : 'bg-emerald-500/8 border-emerald-500/25'
      }`}
    >
      <div className="flex items-center gap-1.5 mb-2">
        {hasIssues
          ? <AlertTriangle className="w-3 h-3 text-amber-400" />
          : <CheckCircle   className="w-3 h-3 text-emerald-400" />
        }
        <p className={`text-[10px] font-semibold ${hasIssues ? 'text-amber-400' : 'text-emerald-400'}`}>
          {hasIssues ? 'Reconciliation Issues Detected' : 'Fully Reconciled'}
        </p>
      </div>
      <div className="space-y-1">
        {turnoverDiff != null && (
          <div className="flex items-center justify-between">
            <span className="text-[9px] text-slate-500">Turnover Gap</span>
            <span className={`text-[9px] font-mono font-semibold ${Math.abs(turnoverDiff) > 0 ? 'text-amber-300' : 'text-emerald-400'}`}>
              ₹{fmtINR(Math.abs(turnoverDiff))}
            </span>
          </div>
        )}
        {itcDiff != null && (
          <div className="flex items-center justify-between">
            <span className="text-[9px] text-slate-500">ITC Gap</span>
            <span className={`text-[9px] font-mono font-semibold ${Math.abs(itcDiff) > 0 ? 'text-amber-300' : 'text-emerald-400'}`}>
              ₹{fmtINR(Math.abs(itcDiff))}
            </span>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Build Part 4 rows from extracted data ─────────────────────────────────────
function buildPart4(d) {
  const HDR = ['Taxable (₹)', 'CGST (₹)', 'SGST (₹)', 'IGST (₹)', 'Cess (₹)']
  const row = (label, desc, pfx, isTotal = false) => ({
    label, desc, headers: HDR, isTotal,
    values: [
      d[`${pfx}_TaxableValue`],
      d[`${pfx}_CGST`],
      d[`${pfx}_SGST`],
      d[`${pfx}_IGST`],
      d[`${pfx}_Cess`],
    ],
  })
  return [
    row('4A', 'B2C Supplies (Unregistered)',       '4A_B2C'),
    row('4B', 'B2B Supplies (Registered)',          '4B_B2B'),
    row('4C', 'Zero-Rated Exports (with tax)',      '4C_Export_WithTax'),
    row('4D', 'SEZ Supplies (with tax)',            '4D_SEZ_WithTax'),
    row('4E', 'Deemed Exports',                     '4E_DeemedExports'),
    row('4F', 'Advances Received/Adjusted',         '4F_Advances'),
    row('4G', 'Inward RCM Supplies',                '4G_RCM_Inward'),
    row('4H', 'Sub-Total (A to G)',                 '4H_SubTotal_AtoG', true),
    row('4I', 'Credit Notes (4H net)',              '4I_CreditNotes'),
    row('4J', 'Debit Notes',                        '4J_DebitNotes'),
    row('4K', 'Amendments (+)',                     '4K_Amendments_Plus'),
    row('4L', 'Amendments (−)',                     '4L_Amendments_Minus'),
    row('4M', 'Sub-Total (I to L)',                 '4M_SubTotal_ItoL', true),
    row('4N', 'Net Tax Payable on Outward',         '4N_Net_TaxPayable', true),
  ]
}

function buildPart5(d) {
  const HDR = ['Taxable Value (₹)']
  const row1 = (label, desc, key) => ({ label, desc, headers: HDR, isTotal: false, values: [d[key]] })
  const row5 = (label, desc, pfx, isTotal = false) => ({
    label, desc, headers: ['Taxable (₹)', 'CGST (₹)', 'SGST (₹)', 'IGST (₹)', 'Cess (₹)'],
    isTotal, values: [d[`${pfx}_TaxableValue`], d[`${pfx}_CGST`], d[`${pfx}_SGST`], d[`${pfx}_IGST`], d[`${pfx}_Cess`]],
  })
  return [
    row1('5A', 'Exports without payment of tax',         '5A_Export_WithoutTax_TaxableValue'),
    row1('5B', 'SEZ without payment of tax',             '5B_SEZ_WithoutTax_TaxableValue'),
    row1('5C', 'RCM (recipient liable)',                 '5C_RCM_Recipient_TaxableValue'),
    row1('5D', 'Exempted Supplies',                      '5D_Exempted_TaxableValue'),
    row1('5E', 'Nil-Rated Supplies',                     '5E_NilRated_TaxableValue'),
    row1('5F', 'Non-GST Supplies',                       '5F_NonGST_TaxableValue'),
    row1('5M', 'Total Non-Taxable Turnover',             '5M_Turnover_NonTaxable_TaxableValue'),
    row5('5N', 'Total Turnover (4N + 5M)',               '5N_TotalTurnover', true),
  ]
}

function buildPart6(d) {
  const HDR = ['CGST (₹)', 'SGST (₹)', 'IGST (₹)', 'Cess (₹)']
  const row = (label, desc, pfx, isTotal = false) => ({
    label, desc, headers: HDR, isTotal,
    values: [d[`${pfx}_CGST`], d[`${pfx}_SGST`], d[`${pfx}_IGST`], d[`${pfx}_Cess`]],
  })
  return [
    row('6A', 'Total ITC as per GSTR-3B',           '6A_ITC_GSTR3B'),
    row('6B-Inp', 'Inputs (Registered)',             '6B_Inputs_Inputs'),
    row('6B-Cap', 'Capital Goods (Registered)',      '6B_Inputs_CapGoods'),
    row('6B-Svc', 'Input Services (Registered)',     '6B_Inputs_InputSvcs'),
    row('6E-Inp', 'Import of Goods (Inputs)',        '6E_Import_Goods_Inputs'),
    row('6F',    'Import of Services',               '6F_Import_Svcs'),
    row('6G',    'ISD Credit',                       '6G_ISD'),
    row('6I',    'Sub-Total (B to H)',               '6I_SubTotal_BtoH', true),
    row('6J',    'Difference (I − A)',               '6J_Difference_IminusA'),
    row('6O',    'Total ITC Availed (I + K + L + M)', '6O_TotalITC', true),
  ]
}

function buildPart7(d) {
  const HDR = ['CGST (₹)', 'SGST (₹)', 'IGST (₹)', 'Cess (₹)']
  const row = (label, desc, pfx, isTotal = false) => ({
    label, desc, headers: HDR, isTotal,
    values: [d[`${pfx}_CGST`], d[`${pfx}_SGST`], d[`${pfx}_IGST`], d[`${pfx}_Cess`]],
  })
  return [
    row('7A', 'Rule 37 (non-payment > 180 days)',   '7A_Rule37'),
    row('7B', 'Rule 39 (ISD reversal)',             '7B_Rule39'),
    row('7C', 'Rule 42 (common credit)',            '7C_Rule42'),
    row('7D', 'Rule 43 (capital goods)',            '7D_Rule43'),
    row('7E', 'Section 17(5) (blocked credits)',   '7E_Sec17_5'),
    row('7H', 'Other Reversals',                   '7H1_OtherReversal'),
    row('7I', 'Total ITC Reversed',                '7I_Total_ITC_Reversed', true),
    row('7J', 'Net ITC Utilizable',                '7J_NetITC_Utilizable', true),
  ]
}

function buildPart9(d) {
  return [
    {
      label: '9A', desc: 'IGST Payable',
      headers: ['Payable (₹)', 'Cash Paid (₹)', 'ITC-CGST (₹)', 'ITC-SGST (₹)', 'ITC-IGST (₹)'],
      isTotal: false,
      values: [d['9A_IGST_Payable'], d['9A_IGST_Cash'], d['9A_IGST_ITC_CGST'], d['9A_IGST_ITC_SGST'], d['9A_IGST_ITC_IGST']],
    },
    {
      label: '9B', desc: 'CGST Payable',
      headers: ['Payable (₹)', 'Cash Paid (₹)', 'ITC-CGST (₹)', 'ITC-IGST (₹)', null, null],
      isTotal: false,
      values: [d['9B_CGST_Payable'], d['9B_CGST_Cash'], d['9B_CGST_ITC_CGST'], d['9B_CGST_ITC_IGST'], null, null],
    },
    {
      label: '9C', desc: 'SGST/UTGST Payable',
      headers: ['Payable (₹)', 'Cash Paid (₹)', 'ITC-SGST (₹)', 'ITC-IGST (₹)', null, null],
      isTotal: false,
      values: [d['9C_SGST_Payable'], d['9C_SGST_Cash'], d['9C_SGST_ITC_SGST'], d['9C_SGST_ITC_IGST'], null, null],
    },
    {
      label: '9E', desc: 'Interest',
      headers: ['Payable (₹)', 'Cash Paid (₹)'],
      isTotal: false,
      values: [d['9E_Interest_Payable'], d['9E_Interest_Cash']],
    },
    {
      label: '9F', desc: 'Late Fee',
      headers: ['Payable (₹)', 'Cash Paid (₹)'],
      isTotal: false,
      values: [d['9F_LateFee_Payable'], d['9F_LateFee_Cash']],
    },
  ]
}

// ── Main panel ────────────────────────────────────────────────────────────────
export default function GSTR9Panel() {
  const { analytics, extractedData, activeFile } = useApp()

  if (!analytics || !activeFile) return null

  const form     = activeFile.gst_type
  const kpis     = analytics.kpis     || []
  const ratios   = analytics.ratios   || []
  const insights = analytics.insights || []
  const d        = extractedData      || {}
  const isRecon  = form === 'GSTR-9C'

  return (
    <div className="space-y-3">

      {/* GSTR-9C reconciliation diff card */}
      {isRecon && <Recon9CSummary data={d} />}

      {/* ── KPIs — always shown (Part-wise detail moved to MOM view) ── */}
      <div>
        <div className="flex items-center gap-1.5 mb-2">
          <BookOpen className="w-3 h-3 text-slate-500 flex-shrink-0" />
          <p className="section-label">
            {isRecon ? 'Reconciliation Statement' : 'Annual Return Summary'}
          </p>
        </div>
        {kpis.length > 0
          ? <KPIGrid kpis={kpis} compact />
          : <p className="text-[10px] text-slate-600 italic px-1">No data extracted</p>
        }
      </div>

      {/* Ratios */}
      {ratios.length > 0 && (
        <div>
          <div className="flex items-center gap-1.5 mb-2">
            <Scale className="w-3 h-3 text-slate-500 flex-shrink-0" />
            <p className="section-label">Key Ratios</p>
          </div>
          <div className="space-y-1.5">
            {ratios.map((r) => (
              <div key={r.name} className="rounded-lg border border-slate-800 bg-slate-900/40 px-3 py-2">
                <div className="flex items-center justify-between gap-2">
                  <p className="text-[10px] text-slate-400 flex-1 min-w-0 leading-tight">{r.name}</p>
                  {r.available
                    ? <span className="text-xs font-bold font-mono text-white flex-shrink-0">{r.value}{r.unit}</span>
                    : <span className="text-[9px] text-slate-600 italic flex-shrink-0">N/A</span>
                  }
                </div>
                {r.benchmark && (
                  <p className="text-[9px] text-slate-600 mt-0.5">
                    <span className="text-slate-500">Benchmark: </span>{r.benchmark}
                  </p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Insights */}
      {insights.length > 0 && (
        <div>
          <div className="flex items-center gap-1.5 mb-2">
            <Lightbulb className="w-3 h-3 text-slate-500 flex-shrink-0" />
            <p className="section-label">Insights & Observations</p>
          </div>
          <div className="space-y-2">
            {insights.map((ins, i) => <InsightItem key={i} text={ins} />)}
          </div>
        </div>
      )}

      <p className="text-[9px] text-slate-700 text-center pt-1 border-t border-slate-800/40">
        {form} · {activeFile.period || 'Annual Period'}
      </p>
    </div>
  )
}
