import { Link } from 'react-router-dom'
import { useState, useEffect, useRef } from 'react'

const SIM_RATE = 720 // 1 real second = 720 sim seconds

export default function Navbar({ metrics = {}, apiOnline, simulationTime }) {
  const [clock, setClock] = useState('--:--:--')
  const baseRef = useRef({ simMs: null, realMs: null })

  useEffect(() => {
    if (simulationTime != null) {
      baseRef.current = { simMs: simulationTime, realMs: Date.now() }
    }
  }, [simulationTime])

  useEffect(() => {
    const tick = () => {
      const { simMs, realMs } = baseRef.current
      if (simMs == null) { setClock(new Date().toLocaleTimeString([], { hour12: false })); return }
      setClock(new Date(simMs + (Date.now() - realMs) * SIM_RATE).toLocaleTimeString([], { hour12: false }))
    }
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [])

  const stats = [
    { val: metrics.shannon    ?? '—', lab: "Shannon H'" },
    { val: metrics.richness   ?? '—', lab: 'Species'    },
    { val: metrics.detections ?? '—', lab: 'Detections' },
    { val: metrics.nodes      ?? '—', lab: 'Nodes'      },
  ]

  return (
    <header
      className="interactive flex items-center rounded-full border"
      style={{
        padding: '10px 20px',
        gap: 0,
        background: 'rgba(255,255,255,0.94)',
        backdropFilter: 'blur(16px)',
        WebkitBackdropFilter: 'blur(16px)',
        boxShadow: '0 4px 24px rgba(0,0,0,0.08), 0 1px 0 rgba(255,255,255,0.8) inset',
        borderColor: 'rgba(255,255,255,0.7)',
      }}
    >
      {/* Brand */}
      <Link to="/" className="flex items-center no-underline flex-shrink-0 group" style={{ gap: 12, paddingRight: 8 }}>
        <div
          className="flex items-center justify-center flex-shrink-0 transition-transform duration-200 group-hover:scale-105"
          style={{
            width: 40, height: 40,
            borderRadius: 12,
            background: 'linear-gradient(135deg, #e6efe9 0%, #c5ddd0 100%)',
            color: '#4a8b71',
          }}
        >
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M19 12c0-3.86-3.14-7-7-7s-7 3.14-7 7v7a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-7Z"/>
            <path d="M8 5L5 2l2 4"/>
            <path d="M16 5l3-3-2 4"/>
            <circle cx="9" cy="12" r="1.5"/>
            <circle cx="15" cy="12" r="1.5"/>
            <path d="M12 14l-1 2h2l-1-2Z" fill="currentColor"/>
          </svg>
        </div>
        <div className="flex flex-col" style={{ lineHeight: 1, gap: 3 }}>
          <span style={{ fontWeight: 700, fontSize: '1rem', color: '#1a202c', letterSpacing: '-0.02em' }}>EchoSense</span>
          <span style={{ fontWeight: 600, fontSize: '0.6rem', color: '#a0aec0', textTransform: 'uppercase', letterSpacing: '0.1em' }}>Biodiversity Monitor</span>
        </div>
      </Link>

      {/* Divider */}
      <div style={{ width: 1, height: 36, background: 'linear-gradient(to bottom,transparent,#e2e8f0,transparent)', margin: '0 20px', flexShrink: 0 }} />

      {/* Metrics */}
      <div className="flex items-center flex-1" style={{ gap: 0 }}>
        {stats.map((s, i) => (
          <div key={i} className="flex items-center">
            {i > 0 && <div style={{ width: 1, height: 24, background: '#e2e8f0', flexShrink: 0 }} />}
            <div
              className="flex flex-col items-center cursor-default transition-colors duration-150 rounded-2xl"
              style={{ padding: '6px 20px' }}
              onMouseEnter={e => e.currentTarget.style.background='#f7f9fa'}
              onMouseLeave={e => e.currentTarget.style.background='transparent'}
            >
              <span style={{ fontWeight: 800, fontSize: '1.35rem', color: '#1a202c', letterSpacing: '-0.03em', lineHeight: 1.1, fontVariantNumeric: 'tabular-nums' }}>
                {s.val}
              </span>
              <span style={{ fontWeight: 700, fontSize: '0.58rem', color: '#a0aec0', textTransform: 'uppercase', letterSpacing: '0.09em', marginTop: 3, whiteSpace: 'nowrap' }}>
                {s.lab}
              </span>
            </div>
          </div>
        ))}

        {/* Sim time chip */}
        <div style={{ width: 1, height: 24, background: '#e2e8f0', flexShrink: 0 }} />
        <div
          className="flex items-center"
          style={{
            gap: 6, margin: '0 12px',
            padding: '7px 14px',
            borderRadius: 9999,
            background: '#f0fdf4',
            border: '1px solid #bbf7d0',
            color: '#4a8b71',
            fontSize: '0.78rem',
            fontWeight: 700,
            letterSpacing: '0.02em',
            fontVariantNumeric: 'tabular-nums',
          }}
        >
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
            <circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>
          </svg>
          {clock}
        </div>
      </div>

      {/* Divider */}
      <div style={{ width: 1, height: 36, background: 'linear-gradient(to bottom,transparent,#e2e8f0,transparent)', margin: '0 20px', flexShrink: 0 }} />

      {/* Actions */}
      <div className="flex items-center flex-shrink-0" style={{ gap: 10 }}>
        <Link
          to="/diversity"
          className="flex items-center no-underline transition-all duration-200 hover:-translate-y-px"
          style={{
            gap: 7, padding: '8px 18px',
            borderRadius: 9999,
            background: '#e6efe9',
            color: '#4a8b71',
            fontSize: '0.8rem',
            fontWeight: 700,
            border: '1.5px solid rgba(74,139,113,0.2)',
          }}
          onMouseEnter={e => { e.currentTarget.style.background='#4a8b71'; e.currentTarget.style.color='#fff'; e.currentTarget.style.boxShadow='0 4px 14px rgba(74,139,113,0.3)' }}
          onMouseLeave={e => { e.currentTarget.style.background='#e6efe9'; e.currentTarget.style.color='#4a8b71'; e.currentTarget.style.boxShadow='none' }}
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
          </svg>
          Diversity Analytics
        </Link>

        <div
          className="flex items-center"
          style={{
            gap: 7, padding: '7px 14px',
            borderRadius: 9999,
            fontSize: '0.74rem',
            fontWeight: 600,
            color: apiOnline ? '#4a8b71' : '#d69e2e',
            background: apiOnline ? '#f0fdf4' : '#fefce8',
            border: `1px solid ${apiOnline ? '#bbf7d0' : '#fde68a'}`,
          }}
        >
          <div className="live-pulse rounded-full flex-shrink-0" style={{ width: 7, height: 7, background: 'currentColor' }} />
          {apiOnline ? 'System Active' : 'Offline Mode'}
        </div>
      </div>
    </header>
  )
}
