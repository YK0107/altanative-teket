import { useEffect, useMemo, useRef, useState } from 'react'
import { seatLabel, seatMap } from '../lib/seats'
import type { SeatDef } from '../types'

interface Props {
  floor: number
  sold: Set<string>
  held: Set<string>
  selected: Set<string>
  onToggle: (seat: SeatDef) => void
}

type VB = [number, number, number, number]
const STAGE_X = 429.4

export function SeatMap({ floor, sold, held, selected, onToggle }: Props) {
  const fdef = seatMap.floors.find((f) => f.f === floor)!
  const seats = useMemo(() => seatMap.seats.filter((s) => s.f === floor), [floor])
  const labels = useMemo(() => seatMap.labels.filter((l) => l.f === floor), [floor])
  const [vb, setVb] = useState<VB>(fdef.viewBox)
  const svgRef = useRef<SVGSVGElement>(null)
  const pointers = useRef(new Map<number, { x: number; y: number }>())
  const gesture = useRef<{ moved: number; seatId: string | null; pinchDist: number }>({ moved: 0, seatId: null, pinchDist: 0 })

  useEffect(() => setVb(fdef.viewBox), [fdef])

  // 画面px → SVG単位の換算係数（preserveAspectRatio=meet）
  const unit = () => {
    const el = svgRef.current!
    const r = el.getBoundingClientRect()
    return Math.max(vb[2] / r.width, vb[3] / r.height)
  }
  const toSvg = (cx: number, cy: number, v: VB = vb) => {
    const r = svgRef.current!.getBoundingClientRect()
    const u = Math.max(v[2] / r.width, v[3] / r.height)
    const ox = v[0] + v[2] / 2 - (r.width * u) / 2
    const oy = v[1] + v[3] / 2 - (r.height * u) / 2
    return [ox + (cx - r.left) * u, oy + (cy - r.top) * u]
  }
  const zoomAt = (cx: number, cy: number, factor: number) => {
    setVb((v) => {
      const minW = fdef.viewBox[2] / 8
      const maxW = fdef.viewBox[2] * 1.2
      const nw = Math.min(maxW, Math.max(minW, v[2] / factor))
      const f = v[2] / nw
      const [px, py] = toSvg(cx, cy, v)
      return [px - (px - v[0]) / f, py - (py - v[1]) / f, nw, v[3] / f]
    })
  }

  useEffect(() => {
    const el = svgRef.current!
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      zoomAt(e.clientX, e.clientY, e.deltaY < 0 ? 1.2 : 1 / 1.2)
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  })

  const onPointerDown = (e: React.PointerEvent) => {
    svgRef.current!.setPointerCapture(e.pointerId)
    pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY })
    if (pointers.current.size === 1) {
      const t = (e.target as Element).closest('[data-id]')
      gesture.current = { moved: 0, seatId: t?.getAttribute('data-id') ?? null, pinchDist: 0 }
    } else {
      gesture.current.seatId = null
    }
  }
  const onPointerMove = (e: React.PointerEvent) => {
    const prev = pointers.current.get(e.pointerId)
    if (!prev) return
    const cur = { x: e.clientX, y: e.clientY }
    if (pointers.current.size === 1) {
      const dx = cur.x - prev.x
      const dy = cur.y - prev.y
      gesture.current.moved += Math.abs(dx) + Math.abs(dy)
      if (gesture.current.moved > 6) {
        const u = unit()
        setVb((v) => [v[0] - dx * u, v[1] - dy * u, v[2], v[3]])
      }
    } else if (pointers.current.size === 2) {
      const [a, b] = [...pointers.current.entries()].map(([id, p]) => (id === e.pointerId ? cur : p))
      const d = Math.hypot(a.x - b.x, a.y - b.y)
      if (gesture.current.pinchDist) zoomAt((a.x + b.x) / 2, (a.y + b.y) / 2, d / gesture.current.pinchDist)
      gesture.current.pinchDist = d
      gesture.current.moved = 999
    }
    pointers.current.set(e.pointerId, cur)
  }
  const onPointerUp = (e: React.PointerEvent) => {
    pointers.current.delete(e.pointerId)
    if (pointers.current.size === 0) {
      const { moved, seatId } = gesture.current
      if (moved <= 6 && seatId) {
        const s = seats.find((x) => x.id === seatId)
        if (s && !sold.has(s.id) && !held.has(s.id)) onToggle(s)
      }
    }
    if (pointers.current.size < 2) gesture.current.pinchDist = 0
  }

  const zoomBtn = (f: number) => {
    const r = svgRef.current!.getBoundingClientRect()
    zoomAt(r.left + r.width / 2, r.top + r.height / 2, f)
  }

  return (
    <div className="seatmap">
      <svg
        ref={svgRef}
        viewBox={vb.join(' ')}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        role="application"
        aria-label={`${fdef.name}座席表`}
      >
        <g className="stage">
          <rect x={STAGE_X - 60} y={fdef.viewBox[1] + 2} width={120} height={14} rx={3} />
          <text x={STAGE_X} y={fdef.viewBox[1] + 11.5}>
            {floor === 1 ? 'ステージ' : 'ステージ方向'}
          </text>
        </g>
        {labels.map((l, i) => (
          <text key={i} className="rowlabel" x={l.x} y={l.y + 1.6}>
            {l.t}
          </text>
        ))}
        {seats.map((s) => {
          const st = sold.has(s.id) ? 'sold' : held.has(s.id) ? 'held' : selected.has(s.id) ? 'sel' : 'free'
          return (
            <g
              key={s.id}
              data-id={s.id}
              className={`seat cat-${s.c} st-${st}`}
              transform={`translate(${s.x} ${s.y}) rotate(${s.rot})`}
            >
              <title>{seatLabel(s)}</title>
              <rect x={-3.3} y={-3.3} width={6.6} height={6.6} rx={1.3} />
              <text y={1.3}>{s.c === 'W' ? '♿' : s.n}</text>
            </g>
          )
        })}
      </svg>
      <div className="zoom">
        <button type="button" onClick={() => zoomBtn(1.5)} aria-label="拡大">
          ＋
        </button>
        <button type="button" onClick={() => zoomBtn(1 / 1.5)} aria-label="縮小">
          －
        </button>
        <button type="button" onClick={() => setVb(fdef.viewBox)} aria-label="全体表示">
          ⤢
        </button>
      </div>
    </div>
  )
}
