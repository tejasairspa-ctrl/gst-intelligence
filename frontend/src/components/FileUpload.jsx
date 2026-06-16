/**
 * FileUpload — Drag-and-drop zone supporting multiple PDFs.
 * Shows upload progress per file. Supports sequential multi-upload.
 */
import React, { useCallback, useRef, useState } from 'react'
import { Upload, FolderOpen, AlertCircle, CheckCircle2, Loader2 } from 'lucide-react'
import { useApp } from '../context/AppContext'

export default function FileUpload({ compact = false }) {
  const { handleUpload, isUploading, uploadProgress } = useApp()
  const [dragOver, setDragOver]     = useState(false)
  const [results, setResults]       = useState([])   // [{name, status, message}]
  const [processing, setProcessing] = useState(false)
  const folderInputRef              = useRef(null)

  const processFiles = useCallback(
    async (files) => {
      if (!files || files.length === 0) return
      setProcessing(true)
      setResults([])

      const fileList = Array.from(files)
      const newResults = []

      for (const file of fileList) {
        if (!file.name.toLowerCase().endsWith('.pdf')) {
          newResults.push({ name: file.name, status: 'error', message: 'Not a PDF file' })
          continue
        }
        newResults.push({ name: file.name, status: 'processing', message: 'Uploading…' })
        setResults([...newResults])
        try {
          const data = await handleUpload(file)
          const idx = newResults.findIndex((r) => r.name === file.name)
          if (idx >= 0) {
            newResults[idx] = {
              name: file.name,
              status: 'success',
              message: `${data.gst_type} — ${data.period || 'period detected'}`,
            }
          }
        } catch (err) {
          const idx = newResults.findIndex((r) => r.name === file.name)
          if (idx >= 0) {
            newResults[idx] = {
              name: file.name,
              status: 'error',
              message: err.message || 'Upload failed',
            }
          }
        }
        setResults([...newResults])
      }
      setProcessing(false)
    },
    [handleUpload]
  )

  const onDrop = useCallback(
    (e) => {
      e.preventDefault()
      setDragOver(false)
      processFiles(e.dataTransfer.files)
    },
    [processFiles]
  )

  const onChange = (e) => processFiles(e.target.files)

  // Folder upload — webkitdirectory gives all files recursively; filter to PDFs
  const onFolderChange = (e) => {
    const pdfs = Array.from(e.target.files).filter(f => f.name.toLowerCase().endsWith('.pdf'))
    processFiles(pdfs)
    e.target.value = ''   // reset so same folder can be re-selected
  }

  if (compact) {
    return (
      <div className={`flex items-center gap-2 ${processing ? 'opacity-50 pointer-events-none' : ''}`}>
        {processing ? (
          <span className="flex items-center gap-1 text-xs text-slate-400">
            <Loader2 className="w-3 h-3 animate-spin" /> Uploading…
          </span>
        ) : (
          <>
            <label className="cursor-pointer text-xs text-blue-400 hover:text-blue-300 transition-colors">
              + Upload another
              <input type="file" accept=".pdf" multiple className="hidden" onChange={onChange} />
            </label>
            <span className="text-slate-700 text-xs">|</span>
            <label className="cursor-pointer flex items-center gap-1 text-xs text-slate-500 hover:text-slate-300 transition-colors">
              <FolderOpen className="w-3 h-3" /> Folder
              <input
                ref={folderInputRef}
                type="file"
                accept=".pdf"
                multiple
                webkitdirectory=""
                directory=""
                className="hidden"
                onChange={onFolderChange}
              />
            </label>
          </>
        )}
      </div>
    )
  }

  return (
    <div className="w-full max-w-2xl mx-auto space-y-4">
      {/* Drop zone */}
      <label
        onDrop={onDrop}
        onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
        onDragLeave={() => setDragOver(false)}
        className={`
          flex flex-col items-center justify-center gap-4 p-10 rounded-2xl border-2 border-dashed
          cursor-pointer transition-all duration-300
          ${dragOver
            ? 'border-blue-400 bg-blue-500/10 scale-[1.01]'
            : 'border-slate-700 bg-slate-900/40 hover:border-slate-500 hover:bg-slate-800/40'}
          ${processing ? 'pointer-events-none opacity-70' : ''}
        `}
      >
        <input type="file" accept=".pdf" multiple onChange={onChange} className="hidden" />

        {processing ? (
          <div className="flex flex-col items-center gap-3 w-full">
            <div className="w-12 h-12 rounded-full border-4 border-blue-500/30 border-t-blue-500 animate-spin" />
            <p className="text-slate-300 font-medium">Processing PDFs…</p>
            <div className="w-full max-w-xs bg-slate-800 rounded-full h-2">
              <div
                className="bg-blue-500 h-2 rounded-full transition-all duration-300"
                style={{ width: `${uploadProgress}%` }}
              />
            </div>
            <p className="text-slate-500 text-sm">{uploadProgress}%</p>
          </div>
        ) : (
          <>
            <div className="w-16 h-16 rounded-2xl bg-blue-600/20 border border-blue-500/30 flex items-center justify-center">
              <Upload className="w-8 h-8 text-blue-400" />
            </div>
            <div className="text-center">
              <p className="text-white font-semibold text-lg">Drop GST PDFs here</p>
              <p className="text-slate-400 text-sm mt-1">or click to browse · multiple files supported</p>
            </div>
            <div className="flex gap-2 flex-wrap justify-center">
              {['GSTR-1', 'GSTR-3B', 'GSTR-9', 'GSTR-9C'].map((t) => (
                <span key={t} className="px-2.5 py-1 bg-slate-800 border border-slate-700 rounded-full text-xs text-slate-400">
                  {t}
                </span>
              ))}
            </div>
            <p className="text-slate-600 text-xs">
              Max 50 MB · Text-based PDFs only · Upload GSTR-1 + GSTR-3B together for auto-reconciliation
            </p>

            {/* Folder upload */}
            <div className="flex items-center gap-2 mt-1">
              <div className="h-px w-12 bg-slate-800" />
              <span className="text-[11px] text-slate-600">or</span>
              <div className="h-px w-12 bg-slate-800" />
            </div>
            <button
              type="button"
              onClick={(e) => { e.preventDefault(); e.stopPropagation(); folderInputRef.current?.click() }}
              className="flex items-center gap-2 px-4 py-2 rounded-lg border border-slate-700 bg-slate-800/60 hover:border-blue-500/50 hover:bg-slate-800 transition-all text-sm text-slate-400 hover:text-slate-200"
            >
              <FolderOpen className="w-4 h-4 text-blue-400" />
              Upload Entire Folder
            </button>
            <p className="text-[10px] text-slate-600 -mt-2">
              Select a folder — all PDFs inside (including sub-folders) will be uploaded automatically
            </p>
            <input
              ref={folderInputRef}
              type="file"
              accept=".pdf"
              multiple
              webkitdirectory=""
              directory=""
              className="hidden"
              onChange={onFolderChange}
            />
          </>
        )}
      </label>

      {/* Per-file results */}
      {results.length > 0 && (
        <div className="space-y-2">
          {results.map((r, i) => (
            <div
              key={i}
              className={`flex items-center gap-2.5 px-4 py-2.5 rounded-xl border text-sm ${
                r.status === 'success'
                  ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400'
                  : r.status === 'error'
                  ? 'bg-rose-500/10 border-rose-500/30 text-rose-400'
                  : 'bg-slate-800/40 border-slate-700/30 text-slate-400'
              }`}
            >
              {r.status === 'success' && <CheckCircle2 className="w-4 h-4 flex-shrink-0" />}
              {r.status === 'error'   && <AlertCircle  className="w-4 h-4 flex-shrink-0" />}
              {r.status === 'processing' && <Loader2  className="w-4 h-4 flex-shrink-0 animate-spin" />}
              <span className="truncate">
                <span className="font-medium">{r.name}</span>
                <span className="opacity-70"> — {r.message}</span>
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
