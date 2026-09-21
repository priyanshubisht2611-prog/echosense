import { useEffect, useRef, useState } from 'react'
import { Chart, BarElement, CategoryScale, LinearScale, Tooltip } from 'chart.js'
import { apiFetchSafe, fetchBirdImageUrl } from '../api'

Chart.register(BarElement, CategoryScale, LinearScale, Tooltip)

const ACCENT = '#4a8b71'
const MONTHS = ['J','F','M','A','M','J','J','A','S','O','N','D']

function BarChart({ data, indexAxis = 'x', labels, height = 'h-40' }) {
  const canvasRef = useRef(null)
  const chartRef = useRef(null)

  useEffect(() => {
    if (!canvasRef.current || !data?.length) return
    if (chartRef.current) {
      chartRef.current.data.datasets[0].data = data
      if (labels) chartRef.current.data.labels = labels
      chartRef.current.update('none')
      return
    }
    const max = Math.max(...data)
    chartRef.current = new Chart(canvasRef.current, {
      type: 'bar',
      data: {
        labels: labels || Array.from({ length: 24 }, (_, i) => i),
        datasets: [{
          label: indexAxis === 'y' ? 'Detections' : 'Avg Detections',
          data,
          backgroundColor: labels
            ? labels.map((_, i) => [`${ACCENT}cc`, `${ACCENT}88`, `${ACCENT}55`][i % 3])
            : data.map(v => `rgba(74,139,113,${0.25 + (v / max) * 0.75})`),
          hoverBackgroundColor: ACCENT,
          borderRadius: 6, borderSkipped: false,
        }],
      },
      options: {
        indexAxis,
        maintainAspectRatio: false,
        animation: { duration: 400 },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: 'rgba(26,32,44,0.88)',
            titleColor: '#fff', bodyColor: 'rgba(255,255,255,0.72)',
            padding: 12, cornerRadius: 12,
            callbacks: indexAxis === 'x' ? { title: ctx => `Hour ${ctx[0].label}:00` } : {},
          },
        },
        scales: {
          x: { grid: indexAxis === 'y' ? { color: '#f1f5f9' } : { display: false }, ticks: { color: '#718096', maxTicksLimit: indexAxis === 'y' ? 5 : 12, font: { size: 10 } }, border: { display: false } },
          y: {
            grid: indexAxis === 'y' ? { display: false } : { color: '#f1f5f9' },
            ticks: { color: '#718096', maxTicksLimit: 5, font: { size: 10 } },
            border: { display: false }
          },
        },
      },
    })
    return () => { chartRef.current?.destroy(); chartRef.current = null }
  }, [data, labels])

  return (
    <div style={{ background: indexAxis === 'x' ? 'linear-gradient(135deg,#f7faf8,#f0f7f3)' : 'transparent', borderRadius: 20, padding: indexAxis === 'x' ? '20px 20px 16px' : '0' }} className={`${height} w-full`}>
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

function Card({ label, value, sub }) {
  return (
    <div style={{ borderRadius: 24, padding: '20px 24px', background: '#f7f9fa' }}>
      <div style={{ fontSize: '0.7rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.1em', color: '#a0aec0', marginBottom: 8 }}>{label}</div>
      <div style={{ fontWeight: 800, fontSize: '1.25rem', color: '#1a202c' }}>
        {value}
        {sub && <span style={{ fontSize: '0.9rem', fontWeight: 500, color: '#718096', marginLeft: 8 }}>{sub}</span>}
      </div>
    </div>
  )
}

export default function SpeciesDetail({ species }) {
  const [pheno, setPheno] = useState(null)
  const [actData, setActData] = useState(null)
  const [nodeData, setNodeData] = useState([])
  const [imgUrl, setImgUrl] = useState(null)
  const [imgLoaded, setImgLoaded] = useState(false)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!species) return
    const name = species.name || species.species
    setPheno(null); setActData(null); setNodeData([]); setImgUrl(null); setImgLoaded(false); setLoading(true)

    fetchBirdImageUrl(name).then(url => setImgUrl(url))
    apiFetchSafe(`/api/analytics/phenology?species=${encodeURIComponent(name)}`).then(setPheno)
    apiFetchSafe(`/api/analytics/activity-curve?species=${encodeURIComponent(name)}`).then(act => setActData(act?.mean_detections || []))
    apiFetchSafe(`/api/detections?species=${encodeURIComponent(name)}&limit=500`).then(dets => {
      if (dets?.length) {
        const counts = {}
        dets.forEach(d => { counts[d.device_id] = (counts[d.device_id] || 0) + 1 })
        setNodeData(Object.entries(counts).sort((a, b) => b[1] - a[1]))
      } else setNodeData([])
      setLoading(false)
    })
  }, [species?.name, species?.species])

  if (!species) return null

  const name = species.name || species.species
  const site = species.site || 'Field Detection'
  const wikiName = name.trim().replace(/\s+/g, '_')
  const iNatName = encodeURIComponent(name.trim())
  const eBirdCode = name.trim().split(/\s+/)[0].toLowerCase()

  return (
    <>
      {/* Bird hero image */}
      <div className="w-full flex-shrink-0 relative overflow-hidden flex items-center justify-center"
           style={{ height: 320, background: '#1a1f2e', borderRadius: '24px 24px 0 0' }}>
        {imgUrl ? (
          <>
            <img src={imgUrl} alt={name} className={`w-full h-full object-contain block transition-opacity duration-500 ${imgLoaded ? 'opacity-100' : 'opacity-0'}`} onLoad={() => setImgLoaded(true)} />
            <div className="absolute inset-x-0 bottom-0" style={{ background: 'linear-gradient(transparent, rgba(0,0,0,0.8))', padding: '60px 32px 32px' }}>
              <div style={{ fontSize: '2.2rem', fontWeight: 800, lineHeight: 1.1, color: '#fff', textShadow: '0 2px 8px rgba(0,0,0,0.5)', marginBottom: 8 }}>{name}</div>
              <div style={{ fontSize: '0.95rem', fontWeight: 500, color: 'rgba(255,255,255,0.85)' }}>📍 {site} · {species.count || 0} detections</div>
            </div>
            <div className="absolute top-4 right-5" style={{ fontSize: '0.75rem', fontStyle: 'italic', color: 'rgba(255,255,255,0.6)' }}>Photo via Wikipedia</div>
          </>
        ) : (
          <div className="flex flex-col items-center gap-4" style={{ color: '#718096' }}>
            <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke={ACCENT} strokeWidth="1.2"><path d="M3 9l1-3 5 2 3-4 3 4 5-2 1 3M3 9c0 7 4 11 9 13 5-2 9-6 9-13" /></svg>
            <span style={{ fontSize: '0.9rem', color: 'rgba(255,255,255,0.5)' }}>Fetching image…</span>
          </div>
        )}
      </div>

      {/* Body */}
      <div style={{ padding: '36px 32px', display: 'flex', flexDirection: 'column', gap: 40 }}>

        {!imgUrl && (
          <div>
            <h2 style={{ fontSize: '2.4rem', fontWeight: 800, lineHeight: 1.1, color: '#1a202c', letterSpacing: '-0.03em', marginBottom: 12 }}>{name}</h2>
            <div style={{ fontSize: '0.95rem', fontWeight: 600, color: '#718096' }}>Primary Region: {site}</div>
          </div>
        )}

        {/* Detections Highlight */}
        <div style={{ borderRadius: 24, padding: '24px 32px', background: '#f7f9fa' }}>
          <div style={{ fontSize: '0.75rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.1em', color: '#a0aec0', marginBottom: 12 }}>Lifetime Detections</div>
          <div style={{ fontSize: '3.6rem', fontWeight: 900, color: ACCENT, lineHeight: 1 }}>{species.count || 0}</div>
        </div>

        {/* Phenology */}
        <div>
          <SectionHeading>Temporal Analysis</SectionHeading>
          {pheno?.first_seen ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 16 }}>
                <Card label="First Seen" value={new Date(pheno.first_seen).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })} />
                <Card label="Last Seen" value={new Date(pheno.last_seen).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })} />
              </div>
              {pheno.peak_14_day_start && (
                <Card label="Peak 14-Day Activity" value={new Date(pheno.peak_14_day_start).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })} sub={`(${pheno.peak_count} det)`} />
              )}
              
              {/* Heatmap */}
              <div style={{ marginTop: 12 }}>
                <div style={{ fontSize: '0.7rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.1em', color: '#a0aec0', marginBottom: 12 }}>Annual Intensity Heatmap</div>
                <div className="heatmap-grid" style={{ height: 40, gap: 6 }}>
                  {pheno.monthly_heatmap.map((v, i) => <div key={i} className="heatmap-cell" style={{ borderRadius: 6, background: `rgba(74,139,113,${Math.max(0.06, v)})` }} title={`${Math.round(v * 100)}%`} />)}
                </div>
                <div className="flex justify-between" style={{ marginTop: 10, padding: '0 8px' }}>
                  {MONTHS.map((m, i) => <span key={i} style={{ fontSize: '0.75rem', fontWeight: 600, color: '#718096' }}>{m}</span>)}
                </div>
              </div>
            </div>
          ) : (
            <div style={{ padding: '20px 0', fontSize: '0.9rem', color: '#a0aec0' }}>{pheno === null ? 'Retrieving ecosystem patterns…' : 'Insufficient data for phenology mapping.'}</div>
          )}
        </div>

        {/* Activity chart */}
        <div>
          <SectionHeading>24-Hour Activity</SectionHeading>
          {actData?.length
            ? <BarChart data={actData} height="h-48" />
            : <div style={{ padding: '20px 0', fontSize: '0.9rem', color: '#a0aec0' }}>Loading activity data…</div>
          }
        </div>

        {/* Node breakdown */}
        <div>
          <SectionHeading>Detected by Nodes</SectionHeading>
          <div style={{ padding: '24px 24px', background: '#f7f9fa', borderRadius: 24 }}>
            {nodeData.length
              ? <BarChart data={nodeData.map(([, v]) => v)} labels={nodeData.map(([id]) => id)} indexAxis="y" height="h-32" />
              : <div style={{ fontSize: '0.9rem', color: '#a0aec0' }}>Loading node data…</div>
            }
          </div>
        </div>

        {/* External links */}
        <div style={{ paddingBottom: 16 }}>
          <SectionHeading>External Resources</SectionHeading>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {[
              { label: 'eBird', abbr: 'eB', href: `https://ebird.org/species/${eBirdCode}` },
              { label: 'iNaturalist', abbr: 'iN', href: `https://www.inaturalist.org/taxa/search?q=${iNatName}` },
              { label: 'Wikipedia', abbr: 'W', href: `https://en.wikipedia.org/wiki/${wikiName}` },
            ].map(({ label, abbr, href }) => (
              <a key={label} href={href} target="_blank" rel="noopener noreferrer"
                 className="flex items-center no-underline transition-all duration-200 border"
                 style={{ gap: 16, padding: '16px 20px', borderRadius: 20, background: '#f7f9fa', borderColor: '#e2e8f0', color: '#2d3748' }}
                 onMouseEnter={e => { e.currentTarget.style.background='#e6efe9'; e.currentTarget.style.color='#4a8b71'; e.currentTarget.style.borderColor='#4a8b7133'; e.currentTarget.style.transform='translateY(-2px)' }}
                 onMouseLeave={e => { e.currentTarget.style.background='#f7f9fa'; e.currentTarget.style.color='#2d3748'; e.currentTarget.style.borderColor='#e2e8f0'; e.currentTarget.style.transform='translateY(0)' }}>
                <div className="flex items-center justify-center flex-shrink-0"
                     style={{ width: 36, height: 36, borderRadius: 10, background: '#e6efe9', color: ACCENT, fontSize: '0.85rem', fontWeight: 800 }}>{abbr}</div>
                <span style={{ flex: 1, fontSize: '1rem', fontWeight: 600 }}>{label}</span>
                <span style={{ fontSize: '1.2rem', color: '#a0aec0' }}>↗</span>
              </a>
            ))}
          </div>
        </div>
      </div>
    </>
  )
}
