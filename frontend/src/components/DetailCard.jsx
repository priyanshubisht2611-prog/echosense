export default function DetailCard({ open, onClose, children }) {
  return (
    <div className={`detail-card interactive ${open ? 'active' : ''}`}>
      <button
        onClick={onClose}
        aria-label="Close"
        className="sticky top-3.5 self-end mx-3.5 mb-[-46px] w-8 h-8 rounded-full flex items-center justify-center cursor-pointer z-10 flex-shrink-0 transition-colors duration-200 border-0"
        style={{
          background: 'rgba(255,255,255,0.9)',
          backdropFilter: 'blur(6px)',
          color: '#718096',
          boxShadow: '0 2px 8px rgba(0,0,0,0.12)',
        }}
        onMouseEnter={e => { e.currentTarget.style.background='#e2e8f0'; e.currentTarget.style.color='#2d3748' }}
        onMouseLeave={e => { e.currentTarget.style.background='rgba(255,255,255,0.9)'; e.currentTarget.style.color='#718096' }}
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
          <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
        </svg>
      </button>
      <div id="detail-content" className="flex flex-col">
        {children}
      </div>
    </div>
  )
}
