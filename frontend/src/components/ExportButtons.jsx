import React from 'react'
import { Download, FileSpreadsheet, FileText, ExternalLink } from 'lucide-react'
import { useApp } from '../context/AppContext'
import { exportExcel, exportPDF } from '../api/client'
import { useNavigate } from 'react-router-dom'

export default function ExportButtons({ compact = false }) {
  const { activeFile } = useApp()
  const navigate = useNavigate()

  if (!activeFile) return null

  return (
    <div className={`flex gap-2 ${compact ? 'flex-col' : 'flex-wrap'}`}>
      <button
        onClick={() => exportExcel(activeFile.id)}
        className={`flex items-center gap-2 px-3 py-2 rounded-lg bg-emerald-600/15 border border-emerald-600/30
                    text-emerald-400 text-xs font-medium hover:bg-emerald-600/25 transition-colors`}
      >
        <FileSpreadsheet className="w-3.5 h-3.5" />
        {compact ? 'Excel' : 'Export Excel'}
      </button>

      <button
        onClick={() => exportPDF(activeFile.id)}
        className={`flex items-center gap-2 px-3 py-2 rounded-lg bg-blue-600/15 border border-blue-600/30
                    text-blue-400 text-xs font-medium hover:bg-blue-600/25 transition-colors`}
      >
        <FileText className="w-3.5 h-3.5" />
        {compact ? 'PDF' : 'CA Report PDF'}
      </button>

      <button
        onClick={() => navigate('/report')}
        className={`flex items-center gap-2 px-3 py-2 rounded-lg bg-purple-600/15 border border-purple-600/30
                    text-purple-400 text-xs font-medium hover:bg-purple-600/25 transition-colors`}
      >
        <ExternalLink className="w-3.5 h-3.5" />
        {compact ? 'Expand' : 'Full Report'}
      </button>
    </div>
  )
}
