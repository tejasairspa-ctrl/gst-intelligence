import React, { useEffect, useRef, useState } from 'react'
import { Send, Sparkles, Bot, User, Zap, FileSpreadsheet, FileText } from 'lucide-react'
import { useApp } from '../context/AppContext'
import FileUpload from './FileUpload'
import GSTR2BCompiler from './GSTR2BCompiler'

// ── Message formatter ─────────────────────────────────────────────────────────

function formatContent(text) {
  // Bold
  text = text.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
  // Headers
  text = text.replace(/<strong>(.*?)<\/strong>:/g, '<h3>$1:</h3>')
  // Bullet lists
  text = text.replace(/^[•\-]\s+(.+)$/gm, '<li>$1</li>')
  text = text.replace(/(<li>[\s\S]*?<\/li>)+/g, (m) => `<ul>${m}</ul>`)
  // Line breaks
  text = text.replace(/\n{2,}/g, '</p><p>')
  text = text.replace(/\n/g, '<br/>')
  text = `<p>${text}</p>`
  text = text.replace(/<p><\/p>/g, '')
  return text
}

// ── Typing indicator ──────────────────────────────────────────────────────────

function TypingDots() {
  return (
    <div className="flex items-center gap-1.5 px-1 py-0.5">
      <span className="typing-dot" />
      <span className="typing-dot" />
      <span className="typing-dot" />
    </div>
  )
}

// ── Single message bubble ─────────────────────────────────────────────────────

function MessageBubble({ msg }) {
  const isUser = msg.role === 'user'

  return (
    <div className={`flex gap-3 animate-slide-up ${isUser ? 'flex-row-reverse' : 'flex-row'}`}>
      {/* Avatar */}
      <div className={`flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center ${
        isUser
          ? 'bg-blue-600'
          : 'bg-slate-800 border border-slate-700'
      }`}>
        {isUser ? <User className="w-4 h-4 text-white" /> : <Bot className="w-4 h-4 text-blue-400" />}
      </div>

      {/* Bubble */}
      <div className={`max-w-[78%] ${isUser ? 'items-end' : 'items-start'} flex flex-col gap-1`}>
        <div className={`px-4 py-3 rounded-2xl text-sm leading-relaxed ${
          isUser
            ? 'bg-blue-600 text-white rounded-tr-sm'
            : 'bg-slate-800/80 border border-slate-700/60 text-slate-200 rounded-tl-sm'
        }`}>
          {isUser ? (
            <p>{msg.content}</p>
          ) : msg.streaming && !msg.content ? (
            <TypingDots />
          ) : (
            <div
              className="ai-response"
              dangerouslySetInnerHTML={{ __html: formatContent(msg.content) }}
            />
          )}
        </div>
        <div className="flex items-center gap-2 px-1">
          <span className="text-[10px] text-slate-600">
            {new Date(msg.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
          </span>
          {/* Direct answer badge */}
          {!isUser && msg.isDirect && !msg.streaming && (
            <span className="flex items-center gap-0.5 text-[9px] text-emerald-500 bg-emerald-500/10 border border-emerald-500/20 px-1.5 py-0.5 rounded-full">
              <Zap className="w-2.5 h-2.5" />
              Direct
            </span>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Suggested questions ───────────────────────────────────────────────────────

const SUGGESTIONS = [
  'What is the total tax liability?',
  'Show me IGST, CGST, SGST breakdown',
  'What is the ITC available?',
  'What is the cash payment?',
  'Explain the ITC utilization ratio',
  'Are there any compliance concerns?',
  'Summarise this return in 3 points',
]

// ── Main chat interface ───────────────────────────────────────────────────────

export default function ChatInterface() {
  const { messages, isStreaming, sendMessage, hasDashboard, handleUpload, isUploading } = useApp()
  const [input, setInput]   = useState('')
  const bottomRef           = useRef(null)
  const inputRef            = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const submit = () => {
    const q = input.trim()
    if (!q || isStreaming) return
    setInput('')
    sendMessage(q)
  }

  const onKey = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }

  // ── Pre-upload landing ──────────────────────────────────────────────────────
  const [landingTab, setLandingTab] = useState('pdf')  // 'pdf' | '2b'

  if (!hasDashboard) {
    return (
      <div className="flex flex-col items-center justify-center h-full px-6 py-10 space-y-6">

        {/* Hero */}
        <div className="text-center space-y-3 max-w-xl">
          <div className="flex items-center justify-center gap-2 mb-4">
            <div className="w-12 h-12 rounded-2xl bg-blue-600 flex items-center justify-center">
              <Sparkles className="w-6 h-6 text-white" />
            </div>
          </div>
          <h1 className="text-3xl font-bold text-white">GST Intelligence</h1>
          <p className="text-slate-400 text-base leading-relaxed">
            Upload GST return PDFs and ask any question about your data.
            Powered by local AI — fully audit-safe, no hallucinations.
          </p>
          <div className="flex gap-2 justify-center text-xs text-slate-500 flex-wrap">
            <span className="px-2.5 py-1 bg-slate-800 rounded-full">🔒 100% Local</span>
            <span className="px-2.5 py-1 bg-slate-800 rounded-full">📊 Auto Analytics</span>
            <span className="px-2.5 py-1 bg-slate-800 rounded-full">⚡ Direct Answers</span>
            <span className="px-2.5 py-1 bg-slate-800 rounded-full">🔄 Auto Reconciliation</span>
          </div>
        </div>

        {/* Tab toggle */}
        <div className="flex items-center bg-slate-900 border border-slate-800 rounded-xl p-1 gap-1">
          <button
            onClick={() => setLandingTab('pdf')}
            className={`flex items-center gap-2 px-4 py-2 text-sm font-semibold rounded-lg transition-all ${
              landingTab === 'pdf'
                ? 'bg-blue-600 text-white shadow-sm'
                : 'text-slate-500 hover:text-slate-300'
            }`}
          >
            <FileText className="w-3.5 h-3.5" />
            GST Returns (PDF)
          </button>
          <button
            onClick={() => setLandingTab('2b')}
            className={`flex items-center gap-2 px-4 py-2 text-sm font-semibold rounded-lg transition-all ${
              landingTab === '2b'
                ? 'bg-violet-600 text-white shadow-sm'
                : 'text-slate-500 hover:text-slate-300'
            }`}
          >
            <FileSpreadsheet className="w-3.5 h-3.5" />
            GSTR-2B Compiler (Excel)
          </button>
        </div>

        {/* Tab content */}
        {landingTab === 'pdf' ? (
          <>
            <FileUpload />
            <div className="text-center space-y-3 max-w-lg">
              <p className="text-xs text-slate-600 uppercase tracking-wider">After upload you can ask…</p>
              <div className="flex flex-wrap gap-2 justify-center">
                {SUGGESTIONS.slice(0, 5).map((s) => (
                  <span key={s} className="px-3 py-1.5 bg-slate-900 border border-slate-800 rounded-full text-xs text-slate-400">
                    {s}
                  </span>
                ))}
              </div>
            </div>
          </>
        ) : (
          <div className="w-full max-w-2xl">
            <GSTR2BCompiler />
          </div>
        )}

      </div>
    )
  }

  // ── Dashboard chat ──────────────────────────────────────────────────────────
  return (
    <div className="flex flex-col h-full">
      {/* Top bar */}
      <div className="px-4 py-2 border-b border-slate-800/60 flex items-center justify-between gap-2">
        <p className="text-xs text-slate-500 truncate">Chat with your GST data</p>
        <FileUpload compact />
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
        {messages.length === 0 && (
          <div className="text-center py-12 text-slate-600 text-sm">
            <Bot className="w-10 h-10 mx-auto mb-3 opacity-30" />
            Ask anything about your GST return
          </div>
        )}
        {messages.map((msg) => (
          <MessageBubble key={msg.id} msg={msg} />
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Quick suggestions */}
      {messages.length <= 1 && (
        <div className="px-4 pb-2 flex gap-2 flex-wrap">
          {SUGGESTIONS.slice(0, 4).map((s) => (
            <button
              key={s}
              onClick={() => sendMessage(s)}
              disabled={isStreaming}
              className="text-xs px-3 py-1.5 bg-slate-800/60 border border-slate-700/60 rounded-full text-slate-400
                         hover:text-white hover:border-blue-500/40 transition-all disabled:opacity-40"
            >
              {s}
            </button>
          ))}
        </div>
      )}

      {/* Input */}
      <div className="px-4 pb-4 pt-2 border-t border-slate-800/60">
        <div className="flex gap-2 items-end">
          <textarea
            ref={inputRef}
            rows={1}
            value={input}
            onChange={(e) => {
              setInput(e.target.value)
              e.target.style.height = 'auto'
              e.target.style.height = Math.min(e.target.scrollHeight, 120) + 'px'
            }}
            onKeyDown={onKey}
            placeholder="Ask about your GST data…"
            disabled={isStreaming}
            className="flex-1 input-field resize-none overflow-hidden min-h-[44px] max-h-[120px] py-3 text-sm"
          />
          <button
            onClick={submit}
            disabled={!input.trim() || isStreaming}
            className="btn-primary w-11 h-11 flex-shrink-0 flex items-center justify-center p-0 rounded-xl"
          >
            {isStreaming
              ? <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              : <Send className="w-4 h-4" />}
          </button>
        </div>
        <p className="text-[10px] text-slate-700 mt-1.5 text-center">
          Numeric questions get instant direct answers · LLM for explanations · Always audit-safe
        </p>
      </div>
    </div>
  )
}
