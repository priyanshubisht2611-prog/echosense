import { useEffect, useRef, useState } from 'react'
import { Chart, BarElement, CategoryScale, LinearScale, Tooltip } from 'chart.js'
import { apiFetchSafe, statusColorHex } from '../api'

Chart.register(BarElement, CategoryScale, LinearScale, Tooltip)

const ACCENT = '#4a8b71'

function BarChart({ data, height = 'h-40' }) {
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
        labels: Array.from({ length: 24 }, (_, i) => i),
        datasets: [{
          label: 'Avg Detections', data,
          backgroundColor: data.map(v => `rgba(74,139,113,${0.25 + (v / max) * 0.75})`),
          hoverBackgroundColor: ACCENT,
          borderRadius: 6, borderSkipped: false,
        }],
      },
      options: {
        maintainAspectRatio: false,
        animation: { duration: 400 },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: 'rgba(26,32,44,0.88)',
            titleColor: '#fff', bodyColor: 'rgba(255,255,255,0.72)',
            padding: 12, cornerRadius: 12,
            callbacks: { title: ctx => `Hour ${ctx[0].label}:00` },
          },
        },
        scales: {
          x: { grid: { display: false }, ticks: { color: '#718096', maxTicksLimit: 12, font: { size: 10 } }, border: { display: false } },
          y: {
            grid: { color: '#f1f5f9' },
            ticks: { display: false },
            border: { display: false },
          },
        },
      },
    })
    return () => { chartRef.current?.destroy(); chartRef.current = null }
  }, [data])

  return (
    <div style={{ background: 'linear-gradient(135deg,#f7faf8,#f0f7f3)', borderRadius: 20, padding: '20px 20px 16px' }} className={`${height} w-full`}>
      <canvas ref={canvasRef} />
    </div>
  )
}

function SectionHeading({ children }) {
  return (
    <div style={{ fontSize: '0.72rem', fontWeight: 800, textTransform: 'uppercase', letterSpacing: '0.1em', color: '#a0aec0', marginBottom: 16 }}>
      {children}
    </div>
  )
}

export default function DeviceDetail({ device, onSpeciesClick }) {
  const [actData, setActData] = useState(null)
  const [recent, setRecent] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!device) return
    setActData(null); setRecent([]); setLoading(true)

    Promise.all([
      apiFetchSafe(`/api/analytics/activity-curve?device_id=${encodeURIComponent(device.id)}`),
      apiFetchSafe(`/api/detections?device_id=${encodeURIComponent(device.id)}&limit=10`),
    ]).then(([act, dets]) => {
      setActData(act?.mean_detections || [])
      setRecent(dets || [])
      setLoading(false)
    })
  }, [device?.id])

  if (!device) return null

  const name = device.site_name || device.id
  const bat = device.battery_pct ?? 0
  const temp = device.temp_c ?? '--'
  const last = device.last_seen ? new Date(device.last_seen).toLocaleString() : 'Just now'
  const hex = statusColorHex(device.status)
  const batColor = bat > 50 ? '#48bb78' : bat > 20 ? '#ecc94b' : '#e53e3e'

  return (
    <div style={{ padding: '36px 32px', display: 'flex', flexDirection: 'column', gap: 36 }}>
      {/* Header */}
      <div>
        <h2 style={{ fontSize: '2.4rem', fontWeight: 800, lineHeight: 1.1, color: '#1a202c', letterSpacing: '-0.03em', marginBottom: 12 }}>{name}</h2>
        <div className="flex items-center" style={{ gap: 10, fontSize: '0.95rem', fontWeight: 600, color: '#718096' }}>
          <div style={{ width: 10, height: 10, borderRadius: '50%', background: hex, boxShadow: `0 0 0 3px ${hex}33` }} />
          <span>Device ID: {device.id}</span>
          <span style={{ color: '#cbd5e0' }}>|</span>
          <span style={{ textTransform: 'uppercase', letterSpacing: '0.05em' }}>{device.status || 'unknown'}</span>
        </div>
      </div>

      {/* Stats grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 16 }}>
        {[
          { label: 'Battery Level', value: (
            <div className="flex items-center" style={{ gap: 12, marginTop: 4 }}>
              <span style={{ fontWeight: 800, fontSize: '1.4rem', color: batColor, fontVariantNumeric: 'tabular-nums' }}>{bat}%</span>
              <div style={{ flex: 1, height: 6, borderRadius: 99, background: '#e2e8f0', overflow: 'hidden' }}>
                <div style={{ height: '100%', width: `${bat}%`, background: batColor, transition: 'width 0.5s ease', borderRadius: 99 }} />
              </div>
            </div>
          )},
          { label: 'Temperature', value: <span style={{ fontWeight: 800, fontSize: '1.4rem', color: '#1a202c' }}>{temp}°C</span> },
          { label: 'Overall Detections', value: <span style={{ fontWeight: 900, fontSize: '2.2rem', color: ACCENT }}>{device.count || 0}</span>, span: true },
          { label: 'Last Check-in', value: <span style={{ fontWeight: 600, fontSize: '1.05rem', color: '#4a5568' }}>{last}</span>, span: true },
        ].map((stat, i) => (
          <div key={i} style={{ borderRadius: 24, padding: '20px 24px', background: '#f7f9fa', gridColumn: stat.span ? 'span 2' : 'auto' }}>
            <div style={{ fontSize: '0.7rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.1em', color: '#a0aec0', marginBottom: 8 }}>{stat.label}</div>
            {stat.value}
          </div>
        ))}
      </div>

      {/* Activity chart */}
      <div>
        <SectionHeading>24h Activity Curve</SectionHeading>
        {loading || !actData?.length
          ? <div style={{ height: 160, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '0.9rem', color: '#a0aec0', background: '#f7f9fa', borderRadius: 24 }}>Loading activity…</div>
          : <BarChart data={actData} height="h-48" />
        }
      </div>

      {/* Recent detections */}
      <div>
        <SectionHeading>Recent Detections</SectionHeading>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {loading && <div style={{ fontSize: '0.9rem', color: '#a0aec0', padding: '20px 0' }}>Loading detections…</div>}
          {!loading && recent.length === 0 && <div style={{ fontSize: '0.9rem', color: '#a0aec0', padding: '20px 0' }}>No detections found.</div>}
          {recent.map((det, i) => {
            const sp = det.species || 'Unknown'
            const initials = sp.split(' ').map(w => w[0]).join('').slice(0, 2).toUpperCase()
            const conf = det.confidence != null ? `${(det.confidence * 100).toFixed(0)}%` : '—'
            const ts = det.timestamp ? new Date(det.timestamp).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—'
            // Rotate colors for variety
            const bg = ['#e6efe9', '#ede9f5', '#fef3ec', '#edf2fb'][i % 4]
            const fg = ['#4a8b71', '#7b6fcc', '#e07b54', '#4a72cc'][i % 4]
            return (
              <div key={i}
                   onClick={() => onSpeciesClick({ name: sp, count: 1, site: name })}
                   className="flex items-center cursor-pointer transition-all duration-200 border"
                   style={{ gap: 16, padding: '16px 20px', borderRadius: 20, borderColor: 'transparent', background: 'transparent' }}
                   onMouseEnter={e => { e.currentTarget.style.background='#f7f9fa'; e.currentTarget.style.borderColor='#e2e8f0' }}
                   onMouseLeave={e => { e.currentTarget.style.background='transparent'; e.currentTarget.style.borderColor='transparent' }}>
                <div className="flex items-center justify-center flex-shrink-0"
                     style={{ width: 44, height: 44, borderRadius: 14, background: bg, color: fg, fontSize: '0.8rem', fontWeight: 800 }}>{initials}</div>
                <div className="flex-1 min-w-0">
                  <div style={{ fontWeight: 700, fontSize: '1rem', color: '#1a202c', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{sp}</div>
                  <div style={{ fontSize: '0.8rem', fontWeight: 500, color: '#718096', marginTop: 4 }}>{ts}</div>
                </div>
                <div className="text-right">
                  <div style={{ fontWeight: 800, fontSize: '1rem', color: ACCENT }}>{conf}</div>
                  <div style={{ fontSize: '0.7rem', fontWeight: 700, color: '#a0aec0', textTransform: 'uppercase', letterSpacing: '0.05em' }}>conf</div>
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
