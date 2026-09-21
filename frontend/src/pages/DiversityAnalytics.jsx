import { useEffect, useState, useRef } from 'react'
import { Link } from 'react-router-dom'
import {
  Chart, LineElement, PointElement, LineController,
  BarElement, BarController, CategoryScale, LinearScale,
  Tooltip, Legend, TimeScale, Filler,
} from 'chart.js'
import 'chartjs-adapter-date-fns'
import { apiFetchSafe, NODES } from '../api'

Chart.register(
  LineElement, PointElement, LineController,
  BarElement, BarController, CategoryScale, LinearScale,
  Tooltip, Legend, TimeScale, Filler,
)

const POLL_MS = 5000

function useChart(ref, buildConfig, deps) {
  const chartRef = useRef(null)
  useEffect(() => {
    if (!ref.current) return
    if (!deps.every(Boolean)) return
    if (chartRef.current) { chartRef.current.destroy(); chartRef.current = null }
    const cfg = buildConfig()
    if (cfg) chartRef.current = new Chart(ref.current, cfg)
    return () => { chartRef.current?.destroy(); chartRef.current = null }
  }, deps) // eslint-disable-line react-hooks/exhaustive-deps
}

export default function DiversityAnalytics() {
  const [totals, setTotals] = useState({ total_species: '—', total_detections: '—' })
  const [nodeDiv, setNodeDiv] = useState([])
  const [shannonHistory, setShannonHistory] = useState([])
  const [richnessHistory, setRichnessHistory] = useState([])
  const [accumData, setAccumData] = useState([])
  const [lastUpdated, setLastUpdated] = useState(null)

  const shannonRef = useRef(null)
  const richnessRef = useRef(null)
  const accumRef = useRef(null)

  useEffect(() => {
    let mounted = true
    const fetchAll = async () => {
      const [div, sHist, rHist, accum] = await Promise.all([
        apiFetchSafe('/api/analytics/diversity'),
        apiFetchSafe('/api/analytics/shannon-timeline'),
        apiFetchSafe('/api/analytics/richness-timeline'),
        apiFetchSafe('/api/analytics/species-accumulation'),
      ])
      if (!mounted) return
      setTotals({ total_species: div?.species_richness ?? '—', total_detections: div?.total_detections ?? '—' })
      setNodeDiv(div?.by_node || [])
      setShannonHistory(sHist || [])
      setRichnessHistory(rHist || [])
      setAccumData(accum || [])
      setLastUpdated(new Date())
    }
    fetchAll()
    const timer = setInterval(fetchAll, POLL_MS)
    return () => { mounted = false; clearInterval(timer) }
  }, [])

  useChart(shannonRef, () => {
    if (!shannonHistory.length) return null
    return {
      type: 'line',
      data: {
        datasets: NODES.map(node => ({
          label: node.id,
          data: shannonHistory.filter(d => d.device_id === node.id).map(d => ({ x: d.date, y: d.shannon_index })),
          borderColor: node.color, backgroundColor: node.color,
          tension: 0.3, pointRadius: 4, pointHoverRadius: 6,
        })),
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false }, tooltip: { mode: 'index', intersect: false, backgroundColor: 'rgba(26,32,44,0.88)', titleColor: '#fff', bodyColor: 'rgba(255,255,255,0.72)', padding: 12, cornerRadius: 10 } },
        scales: {
          x: { type: 'time', time: { unit: 'day', displayFormats: { day: 'MMM d' } }, grid: { display: false }, ticks: { font: { size: 10 } } },
          y: { beginAtZero: true, suggestedMax: 4.0, grid: { color: '#f1f5f9' }, title: { display: true, text: "Shannon Index (H')", color: '#a0aec0', font: { size: 11 } } },
        },
      },
    }
  }, [shannonHistory])

  useChart(richnessRef, () => {
    if (!richnessHistory.length) return null
    return {
      type: 'bar',
      data: {
        datasets: NODES.map(node => ({
          label: node.label,
          data: richnessHistory.filter(d => d.device_id === node.id).map(d => ({ x: d.date, y: d.species_richness })),
          backgroundColor: node.color, borderRadius: 6,
        })),
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { position: 'bottom', labels: { usePointStyle: true, boxWidth: 8, font: { family: 'Inter', size: 11 } } }, tooltip: { backgroundColor: 'rgba(26,32,44,0.88)', titleColor: '#fff', bodyColor: 'rgba(255,255,255,0.72)', padding: 12, cornerRadius: 10 } },
        scales: {
          x: { type: 'time', time: { unit: 'day' }, stacked: true, grid: { display: false }, ticks: { font: { size: 10 } } },
          y: { stacked: true, grid: { color: '#f1f5f9' }, title: { display: true, text: 'Unique Species', color: '#a0aec0', font: { size: 11 } } },
        },
      },
    }
  }, [richnessHistory])

  useChart(accumRef, () => {
    if (!accumData.length) return null
    const aggregated = {}
    accumData.forEach(d => { aggregated[d.first_seen_date] = (aggregated[d.first_seen_date] || 0) + 1 })
    let running = 0
    const curvePoints = Object.keys(aggregated).sort().map(date => ({ x: date, y: (running += aggregated[date]) }))
    return {
      type: 'line',
      data: {
        datasets: [{
          label: 'Cumulative Species', data: curvePoints,
          borderColor: '#4a8b71', backgroundColor: 'rgba(74,139,113,0.1)', fill: true, tension: 0.4,
          pointRadius: 4, pointBackgroundColor: '#fff', pointBorderColor: '#4a8b71', pointBorderWidth: 2,
        }],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false }, tooltip: { backgroundColor: 'rgba(26,32,44,0.88)', titleColor: '#fff', bodyColor: 'rgba(255,255,255,0.72)', padding: 12, cornerRadius: 10 } },
        scales: {
          x: { type: 'time', time: { unit: 'day', displayFormats: { day: 'MMM d' } }, grid: { display: false }, ticks: { font: { size: 10 } } },
          y: { beginAtZero: true, grid: { color: '#f1f5f9' }, title: { display: true, text: 'Total Distinct Species Discovered', color: '#a0aec0', font: { size: 11 } } },
        },
      },
    }
  }, [accumData])

  const enkDiv = nodeDiv.find(n => n.device_id === 'E-NK')?.shannon_index
  const epgDiv = nodeDiv.find(n => n.device_id === 'E-PG')?.shannon_index
  const ekbDiv = nodeDiv.find(n => n.device_id === 'E-KB')?.shannon_index

  return (
    <div className="diversity-page">
      {/* Top nav */}
      <nav className="flex items-center gap-0 bg-white rounded-full mx-7 mt-5 border border-black/[0.06] sticky top-5"
           style={{ padding: '10px 20px', boxShadow: '0 4px 24px rgba(0,0,0,0.06), 0 1px 0 rgba(255,255,255,0.8) inset', zIndex: 100 }}>
        <div className="flex items-center gap-3 flex-shrink-0 pr-2">
          <div className="flex items-center justify-center flex-shrink-0" style={{ width: 40, height: 40, borderRadius: 12, background: '#e6efe9', color: '#4a8b71' }}>
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M19 12c0-3.86-3.14-7-7-7s-7 3.14-7 7v7a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-7Z"/><path d="M8 5L5 2l2 4"/><path d="M16 5l3-3-2 4"/><circle cx="9" cy="12" r="1.5"/><circle cx="15" cy="12" r="1.5"/><path d="M12 14l-1 2h2l-1-2Z" fill="currentColor"/></svg>
          </div>
          <div className="flex flex-col" style={{ lineHeight: 1, gap: 3 }}>
            <span style={{ fontWeight: 700, fontSize: '1rem', color: '#1a202c', letterSpacing: '-0.02em' }}>EchoSense</span>
            <span style={{ fontWeight: 600, fontSize: '0.6rem', color: '#a0aec0', textTransform: 'uppercase', letterSpacing: '0.1em' }}>Biodiversity Monitor</span>
          </div>
        </div>
        <div style={{ width: 1, height: 36, background: '#e2e8f0', margin: '0 20px', flexShrink: 0 }} />
        <div className="flex items-center" style={{ gap: 10 }}>
          <Link to="/" className="flex items-center no-underline transition-colors duration-200" style={{ gap: 8, padding: '10px 20px', borderRadius: 9999, fontSize: '0.82rem', fontWeight: 700, color: '#718096' }} onMouseEnter={e => { e.currentTarget.style.background='#f7f9fa'; e.currentTarget.style.color='#2d3748' }} onMouseLeave={e => { e.currentTarget.style.background='transparent'; e.currentTarget.style.color='#718096' }}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /><polyline points="9 22 9 12 15 12 15 22" /></svg> Live Dashboard
          </Link>
          <div className="flex items-center" style={{ gap: 8, padding: '10px 20px', borderRadius: 9999, background: '#e6efe9', color: '#4a8b71', fontSize: '0.82rem', fontWeight: 700 }}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12" /></svg> Diversity Analytics
          </div>
        </div>
        <div style={{ width: 1, height: 36, background: '#e2e8f0', margin: '0 20px', flexShrink: 0 }} />
        <div className="flex-1" />
        {lastUpdated && <span style={{ fontSize: '0.75rem', fontWeight: 600, color: '#a0aec0', marginRight: 16 }}>Updated {lastUpdated.toLocaleTimeString([], { hour12: false })}</span>}
        <div style={{ padding: '8px 16px', borderRadius: 9999, background: '#f0fdf4', color: '#4a8b71', border: '1px solid #bbf7d0', fontSize: '0.78rem', fontWeight: 700 }}>Analytics Mode</div>
      </nav>

      <div style={{ width: '100%', maxWidth: 1300, margin: '0 auto', padding: '0 40px 80px' }}>
        {/* Page header */}
        <div style={{ paddingTop: 56, paddingBottom: 40, textAlign: 'center' }}>
          <h1 style={{ fontSize: '2.8rem', fontWeight: 900, marginBottom: 12, color: '#1a202c', letterSpacing: '-0.04em' }}>Biodiversity Analytics</h1>
          <p style={{ fontSize: '1.05rem', maxWidth: 800, margin: '0 auto', color: '#718096', lineHeight: 1.6, fontWeight: 500 }}>Shannon diversity, species richness, and accumulation trends across the three EchoSense field monitoring nodes in the Nainital–Kumaon region.</p>
        </div>

        {/* KPI row */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 20, marginBottom: 40 }}>
          {[
            { label: "E-NK Shannon H'", value: enkDiv != null ? Number(enkDiv).toFixed(2) : '—', node: 'Nainital Lake', color: '#4a8b71' },
            { label: "E-PG Shannon H'", value: epgDiv != null ? Number(epgDiv).toFixed(2) : '—', node: 'Pangot Forest', color: '#7b6fcc' },
            { label: "E-KB Shannon H'", value: ekbDiv != null ? Number(ekbDiv).toFixed(2) : '—', node: 'Kilbury Reserve', color: '#e07b54' },
            { label: 'Total Species', value: totals.total_species, node: 'All Nodes', color: '#4a5568' },
            { label: 'Total Detections', value: totals.total_detections, node: 'All Nodes', color: '#4a5568' },
          ].map((kpi, i) => (
            <div key={i} className="bg-white transition-all duration-200 hover:-translate-y-1" style={{ borderRadius: 28, padding: '28px 32px', border: '1px solid #e2e8f0', boxShadow: '0 8px 24px rgba(0,0,0,0.03)' }} onMouseEnter={e => e.currentTarget.style.boxShadow='0 16px 40px rgba(0,0,0,0.08)'} onMouseLeave={e => e.currentTarget.style.boxShadow='0 8px 24px rgba(0,0,0,0.03)'}>
              <div style={{ fontSize: '0.72rem', fontWeight: 800, textTransform: 'uppercase', letterSpacing: '0.1em', color: '#a0aec0', marginBottom: 16 }}>{kpi.label}</div>
              <div style={{ fontSize: '2.8rem', fontWeight: 900, color: '#1a202c', letterSpacing: '-0.04em', lineHeight: 1 }}>{kpi.value}</div>
              <span style={{ display: 'inline-block', marginTop: 16, fontSize: '0.78rem', fontWeight: 700, padding: '4px 12px', borderRadius: 9999, background: `${kpi.color}15`, color: kpi.color }}>{kpi.node}</span>
            </div>
          ))}
        </div>

        {/* Charts row 1 */}
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: 32, marginBottom: 32 }}>
          {[
            {
              title: 'Shannon Diversity Over Time', desc: "Shannon index (H') per node, daily. Higher H' indicates greater ecological diversity.", canvasRef: shannonRef,
              footer: (
                <div className="flex flex-wrap" style={{ gap: 16, marginTop: 24 }}>
                  {NODES.map(n => <div key={n.id} className="flex items-center" style={{ gap: 8, fontSize: '0.85rem', fontWeight: 600, color: '#718096' }}><div style={{ width: 12, height: 12, borderRadius: '50%', background: n.color }} />{n.id} {n.label}</div>)}
                </div>
              ),
              height: 'chart-wrap',
            },
            { title: 'Species Richness Comparison', desc: 'Unique species detected per node, stacked by day.', canvasRef: richnessRef, height: 'chart-wrap' },
          ].map((card, i) => (
            <div key={i} className="bg-white transition-shadow duration-200 hover:shadow-[0_16px_40px_rgba(0,0,0,0.08)]" style={{ borderRadius: 32, padding: '36px 40px', border: '1px solid #e2e8f0', boxShadow: '0 8px 24px rgba(0,0,0,0.03)' }}>
              <div style={{ fontSize: '1.05rem', fontWeight: 800, textTransform: 'uppercase', letterSpacing: '0.05em', color: '#1a202c', marginBottom: 8 }}>{card.title}</div>
              <div style={{ fontSize: '0.9rem', color: '#718096', lineHeight: 1.6, marginBottom: 24 }}>{card.desc}</div>
              <div className={card.height}><canvas ref={card.canvasRef} /></div>
              {card.footer}
            </div>
          ))}
        </div>

        {/* Accumulation chart */}
        <div className="bg-white transition-shadow duration-200 hover:shadow-[0_16px_40px_rgba(0,0,0,0.08)] mb-10" style={{ borderRadius: 32, padding: '36px 40px', border: '1px solid #e2e8f0', boxShadow: '0 8px 24px rgba(0,0,0,0.03)' }}>
          <div style={{ fontSize: '1.05rem', fontWeight: 800, textTransform: 'uppercase', letterSpacing: '0.05em', color: '#1a202c', marginBottom: 8 }}>Species Accumulation Curve</div>
          <div style={{ fontSize: '0.9rem', color: '#718096', lineHeight: 1.6, marginBottom: 24 }}>Cumulative unique species count over time, derived from the first detection date per species across all nodes.</div>
          <div className="chart-wrap-tall"><canvas ref={accumRef} /></div>
        </div>
      </div>
      <footer style={{ textAlign: 'center', padding: '32px 0 40px', fontSize: '0.85rem', fontWeight: 500, color: '#a0aec0' }}>EchoSense Biodiversity Monitoring &mdash; Nainital, Uttarakhand</footer>
    </div>
  )
}
