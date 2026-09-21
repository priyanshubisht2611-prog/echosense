import { useEffect, useRef } from 'react'
import { Chart, BarElement, CategoryScale, LinearScale, Tooltip } from 'chart.js'
import { statusColorHex } from '../api'

Chart.register(BarElement, CategoryScale, LinearScale, Tooltip)

const ACCENT = '#4a8b71'
const DEFAULT_ACT = [12, 5, 2, 1, 15, 60, 110, 80, 45, 30, 25, 20, 18, 22, 35, 50, 95, 120, 80, 40, 25, 18, 15, 10]

/* ── Shared colours for species initials ── */
const PALETTE_BG = ['#e6efe9', '#ede9f5', '#fef3ec', '#edf2fb']
const PALETTE_FG = ['#4a8b71', '#7b6fcc', '#e07b54', '#4a72cc']

function SectionLabel({ children, count }) {
  return (
    <div className="flex items-center justify-between" style={{ marginBottom: 12 }}>
      <span style={{ fontSize: '0.65rem', fontWeight: 800, textTransform: 'uppercase', letterSpacing: '0.1em', color: '#a0aec0' }}>
        {children}
      </span>
      {count != null && (
        <span style={{ fontSize: '0.65rem', fontWeight: 700, padding: '2px 8px', borderRadius: 9999, background: '#e6efe9', color: ACCENT }}>
          {count}
        </span>
      )}
    </div>
  )
}

function ActivityChart({ data }) {
  const canvasRef = useRef(null)
  const chartRef = useRef(null)

  useEffect(() => {
    if (!canvasRef.current || !data?.length) return
    if (chartRef.current) {
      chartRef.current.data.datasets[0].data = data
      chartRef.current.update('none')
      return
    }
    const max = Math.max(...data)
    chartRef.current = new Chart(canvasRef.current, {
      type: 'bar',
      data: {
        labels: Array.from({ length: 24 }, (_, i) => i % 6 === 0 ? `${i}:00` : ''),
        datasets: [{
          data,
          backgroundColor: data.map(v => `rgba(74,139,113,${0.25 + (v / max) * 0.75})`),
          hoverBackgroundColor: ACCENT,
          borderRadius: 4,
          borderSkipped: false,
        }],
      },
      options: {
        maintainAspectRatio: false,
        animation: { duration: 500 },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: 'rgba(26,32,44,0.88)',
            titleColor: '#fff',
            bodyColor: 'rgba(255,255,255,0.72)',
            padding: 10,
            cornerRadius: 10,
            callbacks: {
              title: ctx => `${ctx[0].dataIndex}:00 – ${ctx[0].dataIndex + 1}:00`,
              label: ctx => ` ${ctx.parsed.y} avg detections`,
            },
          },
        },
        scales: {
          x: { grid: { display: false }, ticks: { color: '#cbd5e0', font: { size: 9 }, maxRotation: 0 }, border: { display: false } },
          y: { grid: { color: 'rgba(226,232,240,0.5)' }, ticks: { display: false }, border: { display: false } },
        },
      },
    })
    return () => { chartRef.current?.destroy(); chartRef.current = null }
  }, [data])

  return (
    <div style={{ background: 'linear-gradient(135deg,#f7faf8,#f0f7f3)', borderRadius: 16, padding: '14px 14px 10px' }}>
      <div style={{ height: 120 }}><canvas ref={canvasRef} /></div>
    </div>
  )
}

function NodeRow({ device, onClick }) {
  const name = device.site_name || device.id
  const hex = statusColorHex(device.status)
  const bat = device.battery_pct ?? 0
  const batColor = bat > 50 ? '#48bb78' : bat > 20 ? '#ecc94b' : '#e53e3e'
  const isOnline = device.status === 'online'

  return (
    <div
      onClick={onClick}
      className="flex items-center transition-all duration-150 cursor-pointer rounded-2xl border"
      style={{ gap: 14, padding: '12px 14px', borderColor: 'transparent', background: 'transparent' }}
      onMouseEnter={e => { e.currentTarget.style.background='#f7f9fa'; e.currentTarget.style.borderColor='#e8edf2' }}
      onMouseLeave={e => { e.currentTarget.style.background='transparent'; e.currentTarget.style.borderColor='transparent' }}
    >
      {/* Icon with online dot */}
      <div className="relative flex-shrink-0">
        <div className="flex items-center justify-center" style={{ width: 40, height: 40, borderRadius: 12, background: `${hex}18`, color: hex }}>
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83" />
          </svg>
        </div>
        {isOnline && (
          <div style={{ position: 'absolute', top: -2, right: -2, width: 10, height: 10, borderRadius: '50%', background: hex, border: '2px solid white' }} />
        )}
      </div>

      {/* Name + battery */}
      <div className="flex-1 min-w-0" style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        <div style={{ fontWeight: 600, fontSize: '0.9rem', color: '#1a202c', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{name}</div>
        <div className="flex items-center" style={{ gap: 8 }}>
          <div style={{ width: 48, height: 5, borderRadius: 99, background: '#e2e8f0', overflow: 'hidden', flexShrink: 0 }}>
            <div style={{ height: '100%', width: `${bat}%`, borderRadius: 99, background: batColor, transition: 'width 0.5s ease' }} />
          </div>
          <span style={{ fontSize: '0.7rem', fontWeight: 600, color: '#a0aec0' }}>{bat}%</span>
          <span style={{ fontSize: '0.68rem', fontWeight: 600, color: hex, display: 'flex', alignItems: 'center', gap: 3 }}>
            <span style={{ width: 5, height: 5, borderRadius: '50%', background: hex, display: 'inline-block' }} />
            {device.status || 'unknown'}
          </span>
        </div>
      </div>

      {/* Detection count */}
      <div className="flex-shrink-0 text-right" style={{ minWidth: 36 }}>
        <div style={{ fontWeight: 900, fontSize: '1.15rem', color: ACCENT, lineHeight: 1.1 }}>{device.count ?? 0}</div>
        <div style={{ fontSize: '0.6rem', fontWeight: 700, color: '#a0aec0', textTransform: 'uppercase', letterSpacing: '0.06em' }}>det</div>
      </div>
    </div>
  )
}

function SpeciesRow({ sp, onClick }) {
  const name = sp.species || sp.name
  const initials = name.split(' ').map(w => w[0]).join('').slice(0, 2).toUpperCase()
  const idx = name.charCodeAt(0) % 4

  return (
    <div
      onClick={onClick}
      className="flex items-center transition-all duration-150 cursor-pointer rounded-2xl border"
      style={{ gap: 14, padding: '11px 14px', borderColor: 'transparent', background: 'transparent' }}
      onMouseEnter={e => { e.currentTarget.style.background='#f7f9fa'; e.currentTarget.style.borderColor='#e8edf2' }}
      onMouseLeave={e => { e.currentTarget.style.background='transparent'; e.currentTarget.style.borderColor='transparent' }}
    >
      <div
        className="flex items-center justify-center flex-shrink-0"
        style={{ width: 40, height: 40, borderRadius: 12, background: PALETTE_BG[idx], color: PALETTE_FG[idx], fontWeight: 700, fontSize: '0.78rem' }}
      >
        {initials}
      </div>
      <div className="flex-1 min-w-0">
        <div style={{ fontWeight: 600, fontSize: '0.88rem', color: '#1a202c', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{name}</div>
        <div style={{ fontSize: '0.7rem', color: '#a0aec0', marginTop: 3, fontStyle: 'italic' }}>{sp.site || 'Field Detector'}</div>
      </div>
      <div
        className="flex-shrink-0 text-center"
        style={{ minWidth: 38, padding: '4px 8px', borderRadius: 99, background: `${ACCENT}14`, color: ACCENT, fontWeight: 800, fontSize: '0.82rem' }}
      >
        {sp.count}
      </div>
    </div>
  )
}

export default function SidePanel({ devices, species, activityData, onDeviceClick, onSpeciesClick }) {
  return (
    <aside
      className="justify-self-end flex flex-col overflow-hidden max-h-full interactive"
      style={{
        width: 400,
        borderRadius: 24,
        background: 'rgba(255,255,255,0.93)',
        backdropFilter: 'blur(16px)',
        WebkitBackdropFilter: 'blur(16px)',
        boxShadow: '0 8px 32px rgba(0,0,0,0.09), 0 1px 0 rgba(255,255,255,0.8) inset',
        border: '1px solid rgba(255,255,255,0.65)',
      }}
    >
      {/* Activity chart */}
      <div style={{ padding: '20px 20px 18px', borderBottom: '1px solid #f0f4f8' }}>
        <SectionLabel>24h Activity Curve</SectionLabel>
        <ActivityChart data={activityData || DEFAULT_ACT} />
      </div>

      {/* Nodes */}
      <div style={{ padding: '18px 20px 16px', borderBottom: '1px solid #f0f4f8' }}>
        <SectionLabel count={devices.length}>Active Field Nodes</SectionLabel>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          {devices.length === 0
            ? <div style={{ textAlign: 'center', padding: '16px 0', fontSize: '0.82rem', color: '#cbd5e0' }}>Awaiting nodes…</div>
            : devices.map(d => <NodeRow key={d.id} device={d} onClick={() => onDeviceClick(d)} />)
          }
        </div>
      </div>

      {/* Species */}
      <div style={{ padding: '18px 20px 16px', flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        <SectionLabel count={species.length}>Recent Detections</SectionLabel>
        <div style={{ flex: 1, overflowY: 'auto', marginRight: -4, paddingRight: 4, scrollbarWidth: 'thin', scrollbarColor: '#e2e8f0 transparent' }}>
          {species.length === 0
            ? <div style={{ textAlign: 'center', padding: '20px 0', fontSize: '0.82rem', color: '#cbd5e0' }}>No detections yet…</div>
            : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                {species.map((s, i) => {
                  const name = s.species || s.name
                  return <SpeciesRow key={i} sp={s} onClick={() => onSpeciesClick({ name, count: s.count, site: s.site || 'Field Detector' })} />
                })}
              </div>
            )
          }
        </div>
      </div>
    </aside>
  )
}
