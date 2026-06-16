/**
 * GSTR2BCompiler — standalone panel for compiling monthly GSTR-2B Excel files.
 * Used on both the landing page and the dashboard (2B tab).
 */
import React, { useState, useRef } from 'react'
import { FileSpreadsheet } from 'lucide-react'
import { compileGSTR2B } from '../api/client'

export default function GSTR2BCompiler() {
  const [files, setFiles]       = useState([])
  const [dragging, setDragging] = useState(false)
  const [status, setStatus]     = useState('idle')  // idle | compiling | done | error
  const [errMsg, setErrMsg]     = useState('')
  const inputRef                = useRef(null)

  const addFiles = (incoming) => {
    const xlsx = Array.from(incoming).filter((f) => f.name.toLowerCase().endsWith('.xlsx'))
    if (!xlsx.length) return
    setFiles((prev) => {
      const existing = new Set(prev.map((f) => f.name))
      const fresh    = xlsx.filter((f) => !existing.has(f.name))
      return [...prev, ...fresh].slice(0, 12)
    })
    setStatus('idle')
  }

  const removeFile = (idx) => setFiles((prev) => prev.filter((_, i) => i !== idx))

  const handleDrop = (e) => {
    e.preventDefault()
    setDragging(false)
    addFiles(e.dataTransfer.files)
  }

  const handleCompile = async () => {
    if (!files.length) return
    setStatus('compiling')
    setErrMsg('')
    try {
      const { url, name } = await compileGSTR2B(files)
      const a = document.createElement('a')
      a.href     = url
      a.download = name
      a.click()
      URL.revokeObjectURL(url)
      setStatus('done')
    } catch (err) {
      setErrMsg(err.message || 'Compilation failed')
      setStatus('error')
    }
  }

  return (
    <div className="space-y-5 w-full max-w-2xl mx-auto">

      {/* Drop zone */}
      <div
        onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
        onClick={() => inputRef.current?.click()}
        className={`flex flex-col items-center justify-center gap-2 px-6 py-10 rounded-xl border-2 border-dashed cursor-pointer transition-all ${
          dragging
            ? 'border-violet-500 bg-violet-500/10'
            : 'border-slate-700 bg-slate-900/50 hover:border-slate-600 hover:bg-slate-900'
        }`}
      >
        <FileSpreadsheet className="w-8 h-8 text-violet-400" />
        <p className="text-sm text-slate-300 font-medium">
          Drop GSTR-2B <span className="text-violet-400">.xlsx</span> files here
        </p>
        <p className="text-xs text-slate-500">or click to browse · up to 12 files (one per month)</p>
        <input
          ref={inputRef}
          type="file"
          accept=".xlsx"
          multiple
          className="hidden"
          onChange={(e) => addFiles(e.target.files)}
        />
      </div>

      {/* File list */}
      {files.length > 0 && (
        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">
              {files.length} / 12 file(s) queued
            </span>
            <button
              onClick={() => { setFiles([]); setStatus('idle') }}
              className="text-[10px] text-slate-600 hover:text-red-400 transition-colors"
            >
              Clear all
            </button>
          </div>
          <div className="rounded-lg border border-slate-800 overflow-hidden">
            {files.map((f, idx) => (
              <div
                key={f.name + idx}
                className={`flex items-center gap-3 px-3 py-2 text-[11px] ${
                  idx % 2 === 0 ? 'bg-slate-900' : 'bg-slate-900/60'
                }`}
              >
                <FileSpreadsheet className="w-3.5 h-3.5 text-emerald-400 flex-shrink-0" />
                <span className="flex-1 text-slate-300 truncate">{f.name}</span>
                <span className="text-slate-600 whitespace-nowrap">
                  {(f.size / 1024).toFixed(0)} KB
                </span>
                <button
                  onClick={(e) => { e.stopPropagation(); removeFile(idx) }}
                  className="text-slate-700 hover:text-red-400 transition-colors ml-1 leading-none"
                  title="Remove"
                >
                  ✕
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Action row */}
      <div className="flex items-center gap-3 flex-wrap">
        <button
          onClick={handleCompile}
          disabled={!files.length || status === 'compiling'}
          className={`flex items-center gap-2 px-5 py-2.5 text-sm font-semibold rounded-lg transition-all ${
            files.length && status !== 'compiling'
              ? 'bg-violet-600 hover:bg-violet-500 text-white shadow-md'
              : 'bg-slate-800 text-slate-600 cursor-not-allowed'
          }`}
        >
          <FileSpreadsheet className="w-4 h-4" />
          {status === 'compiling' ? 'Compiling…' : 'Compile & Download'}
        </button>

        {status === 'done' && (
          <span className="text-[12px] text-emerald-400 font-medium">✓ Download started</span>
        )}
        {status === 'error' && (
          <span className="text-[12px] text-red-400">✗ {errMsg}</span>
        )}
      </div>

      {/* Info box */}
      <div className="rounded-lg border border-slate-800 bg-slate-900/40 px-4 py-3 space-y-1.5">
        <p className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">What gets compiled</p>
        <p className="text-[11px] text-slate-500">
          Sheets 1–5 (Read Me + ITC summaries) are skipped. The 24 data sheets below are stacked
          across all months, with a <span className="text-amber-400 font-medium">Period</span> column prepended to every row.
        </p>
        <div className="grid grid-cols-3 gap-x-4 gap-y-0.5 pt-1">
          {[
            'B2B','B2BA','B2B-CDNR','B2B-CDNRA',
            'ECO','ECOA','ISD','ISDA',
            'IMPG','IMPGA','IMPGSEZ','IMPGSEZA',
            'B2B (ITC Reversal)','B2BA (ITC Reversal)','B2B-DNR','B2B-DNRA',
            'B2B(Rejected)','B2BA(Rejected)','B2B-CDNR(Rejected)','B2B-CDNRA(Rejected)',
            'ECO(Rejected)','ECOA(Rejected)','ISD(Rejected)','ISDA(Rejected)',
          ].map((s) => (
            <span key={s} className="text-[10px] text-slate-600 font-mono">{s}</span>
          ))}
        </div>
      </div>

    </div>
  )
}
