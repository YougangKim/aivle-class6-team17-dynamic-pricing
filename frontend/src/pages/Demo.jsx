import { useEffect, useMemo, useRef, useState } from "react";
import { Play, Pause, RotateCcw, CheckCircle2, Zap, Users, TrendingUp, Store, AlertTriangle, SkipForward, Flame, Clock } from "lucide-react";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine, Legend } from "recharts";
import { Panel } from "../components/ui";
import { CHART } from "../lib/chart";

/* ==================================================================
   FreshWatch 라이브 · 매장 디지털 트윈 + AI 다이나믹 프라이싱
   ① 아이소메트릭 3D 매장(실제 동선) — 시간·고객이 계속 흐름
   ② 폐기위험 품목이 랜덤으로 계속 발생(큐) → 블리(AI) 감지·추천
   ③ 승인 시 '다이나믹 프라이싱' 적용 — 마감까지 가격이 단계적으로 자동 인하
      (ESL 실시간 가격 변동 · 매대 라벨에 현재 인하율 표시)
   ④ 추천 근거(순이익 곡선) · 가격 경로 · What-if(최대 인하율) · 수요예측
   ⑤ 동선 히트맵 · 요일 프리셋 · 도입 ROI 계산기
   ================================================================== */

const BASE = import.meta.env.BASE_URL || "/";
const W = 1000, H = 563;
const OPEN = 540, CLOSE = 1320;
const MAX_AGENTS = 90;
const WALK = 0.085;
const SEC_TO_MIN = 3;

const PROFILES = {
  평일:   [0.04, 0.055, 0.065, 0.07, 0.072, 0.076, 0.085, 0.09, 0.096, 0.096, 0.09, 0.085, 0.08],
  금요일: [0.035, 0.045, 0.055, 0.06, 0.065, 0.07, 0.078, 0.085, 0.1, 0.11, 0.11, 0.105, 0.082],
  주말:   [0.04, 0.07, 0.09, 0.09, 0.1, 0.1, 0.095, 0.095, 0.09, 0.075, 0.065, 0.05, 0.04],
};
const DAY_VOLUME = { 평일: 1.0, 금요일: 1.29, 주말: 1.15 };

const ZONES = [
  { id: "produce", label: "채소",       kind: "wood", price: 3980,  flow: 1, x: 0.04, y: 0.28, w: 0.13, h: 0.22, access: { x: 0.22, y: 0.42 }, dot: ["#4f8d4e", "#78a849", "#a7c957"] },
  { id: "fruit",   label: "과일",       kind: "wood", price: 8900,  flow: 2, x: 0.04, y: 0.56, w: 0.13, h: 0.18, access: { x: 0.22, y: 0.64 }, dot: ["#e6553f", "#f4a261", "#e9c46a"] },
  { id: "meat",    label: "정육·한우",  kind: "cold", price: 52000, flow: 4, x: 0.40, y: 0.06, w: 0.17, h: 0.12, access: { x: 0.485, y: 0.27 }, dot: ["#d46f75", "#e8a0a6", "#f1b5aa"] },
  { id: "seafood", label: "수산",       kind: "cold", price: 15800, flow: 5, x: 0.60, y: 0.06, w: 0.17, h: 0.12, access: { x: 0.685, y: 0.27 }, dot: ["#5b8db0", "#8fb5cf", "#b5d7df"] },
  { id: "dairy",   label: "유제품",     kind: "cold", price: 4850,  flow: 3, x: 0.20, y: 0.06, w: 0.17, h: 0.12, access: { x: 0.285, y: 0.27 }, dot: ["#eef0e0", "#dfe6ee", "#cbd5e1"] },
  { id: "bakery",  label: "베이커리",   kind: "wood", price: 5900,  flow: 6, x: 0.32, y: 0.40, w: 0.13, h: 0.15, access: { x: 0.385, y: 0.60 }, dot: ["#d9a066", "#e6c27a", "#c98a52"] },
  { id: "deli",    label: "델리",       kind: "warm", price: 7500,  flow: 7, x: 0.52, y: 0.40, w: 0.13, h: 0.15, access: { x: 0.585, y: 0.60 }, dot: ["#e0a458", "#d98f65", "#caa06a"] },
  { id: "chilled", label: "냉장간편식", kind: "cold", price: 6900,  flow: 8, x: 0.73, y: 0.28, w: 0.12, h: 0.30, access: { x: 0.67, y: 0.46 }, dot: ["#8fb8c9", "#a9cbd6", "#cfe3e8"] },
];
const ZI = Object.fromEntries(ZONES.map((z, i) => [z.id, i]));

const POOL = [
  { name: "한우 등심 1++", zone: "meat",    weight: "300g",  price: 52000, costR: 0.72, base: 0.30, elas: 1.15, emoji: "🥩" },
  { name: "삼겹살",        zone: "meat",    weight: "500g",  price: 15900, costR: 0.68, base: 0.34, elas: 1.25, emoji: "🥓" },
  { name: "LA꽃갈비",      zone: "meat",    weight: "700g",  price: 39900, costR: 0.70, base: 0.28, elas: 1.10, emoji: "🍖" },
  { name: "국산 고등어",   zone: "seafood", weight: "2마리", price: 9900,  costR: 0.60, base: 0.32, elas: 1.30, emoji: "🐟" },
  { name: "광어회",        zone: "seafood", weight: "400g",  price: 29900, costR: 0.66, base: 0.26, elas: 1.35, emoji: "🍣" },
  { name: "손질 오징어",   zone: "seafood", weight: "3마리", price: 12900, costR: 0.58, base: 0.33, elas: 1.20, emoji: "🦑" },
  { name: "설향 딸기",     zone: "fruit",   weight: "500g",  price: 12900, costR: 0.55, base: 0.36, elas: 1.40, emoji: "🍓" },
  { name: "샤인머스캣",    zone: "fruit",   weight: "1송이", price: 16900, costR: 0.58, base: 0.30, elas: 1.25, emoji: "🍇" },
  { name: "유기농 우유",   zone: "dairy",   weight: "900ml", price: 3200,  costR: 0.62, base: 0.40, elas: 1.10, emoji: "🥛" },
  { name: "그릭요거트",    zone: "dairy",   weight: "400g",  price: 6900,  costR: 0.55, base: 0.35, elas: 1.15, emoji: "🥣" },
  { name: "버터 크루아상", zone: "bakery",  weight: "4개",   price: 7900,  costR: 0.50, base: 0.38, elas: 1.30, emoji: "🥐" },
  { name: "모둠초밥",      zone: "deli",    weight: "12pc",  price: 13900, costR: 0.55, base: 0.30, elas: 1.35, emoji: "🍱" },
  { name: "우렁된장 도시락", zone: "deli",  weight: "1개",   price: 5900,  costR: 0.52, base: 0.40, elas: 1.25, emoji: "🍲" },
  { name: "컷팅 수박",     zone: "produce", weight: "1/4통", price: 6900,  costR: 0.50, base: 0.34, elas: 1.30, emoji: "🍉" },
  { name: "새송이버섯",    zone: "produce", weight: "300g",  price: 2980,  costR: 0.50, base: 0.42, elas: 1.10, emoji: "🍄" },
  { name: "1인 밀키트",    zone: "chilled", weight: "2인",   price: 11900, costR: 0.55, base: 0.33, elas: 1.20, emoji: "🥘" },
];

const AGENT_COLORS = ["#5fd0b5", "#f4bf63", "#7aa7f7", "#d984ad", "#9cce6a", "#d58f65", "#6ec6c9", "#e08b8b"];
const RATES = Array.from({ length: 41 }, (_, i) => i);   // 0~40% 1단위
const won = (n) => Math.round(n).toLocaleString("ko-KR");
const wonShort = (v) => {
  v = Math.round(v);
  if (v >= 1e8) return (v / 1e8).toFixed(1) + "억";
  if (v >= 1e4) return Math.round(v / 1e4).toLocaleString() + "만";
  return v.toLocaleString();
};

/* 다이나믹 프라이싱: 마감(22시)에 가까울수록 cap까지 단계적으로 인하 */
const fracOf = (min) => Math.max(0, Math.min(1, (min - OPEN) / (CLOSE - OPEN)));
const round10 = (v) => Math.round(v / 10) * 10;
const curRate = (min, cap) => Math.min(cap, Math.round(cap * fracOf(min)));   // 1% 단위 인하

let RNG = 987654321;
const rand = () => { RNG = (RNG * 1103515245 + 12345) & 0x7fffffff; return RNG / 0x7fffffff; };
let UID = 0;

function makeAlert(base) {
  const stock = 22 + Math.floor(rand() * 24);
  return { ...base, uid: ++UID, zi: ZI[base.zone], stock, dday: rand() < 0.62 ? 0 : 1 };
}
function pickAlert(queue, activeZis) {
  const cand = POOL.filter((p) => !queue.some((q) => q.zi === ZI[p.zone]) && !activeZis.has(ZI[p.zone]));
  if (!cand.length) return null;
  return makeAlert(cand[Math.floor(rand() * cand.length)]);
}

const costOf = (it) => it.price * it.costR;
const soldFrac = (it, r) => Math.max(0, Math.min(1, it.base + it.elas * (r / 100)));
function netProfit(it, r) {
  const units = it.stock * soldFrac(it, r);
  const margin = it.price * (1 - r / 100) - costOf(it);
  const waste = (it.stock - units) * costOf(it);
  return units * margin - waste;
}
function profitCurve(it) { return RATES.map((r) => ({ rate: r, net: Math.round(netProfit(it, r)) })); }
function bestRate(it) {
  let best = 0, bv = -Infinity;
  for (const r of RATES) { const v = netProfit(it, r); if (v > bv) { bv = v; best = r; } }
  return best;
}
const wastePacksAt = (it, r) => Math.round(it.stock - it.stock * soldFrac(it, r));
const savedWon = (it, r) => Math.max(0, wastePacksAt(it, 0) - wastePacksAt(it, r)) * costOf(it);
const it_units = (it, r) => Math.round(it.stock * soldFrac(it, r));

/* 시간대별 자동 인하 가격 경로 */
function pricePath(it, cap) {
  const hs = [9, 11, 13, 15, 17, 18, 19, 20, 21, 22];
  return hs.map((h) => ({ h: `${h}시`, 가격: round10(it.price * (1 - curRate(h * 60, cap) / 100)) }));
}
function salesCurve(it, cap) {
  const hours = ["09", "11", "13", "15", "17", "18", "19", "20", "21", "22"];
  const u0 = it.stock * soldFrac(it, 0), ur = it.stock * soldFrac(it, cap);
  const sBase = [0.05, 0.13, 0.24, 0.36, 0.5, 0.6, 0.72, 0.84, 0.94, 1];
  const sDisc = [0.03, 0.08, 0.15, 0.24, 0.36, 0.52, 0.7, 0.86, 0.96, 1];
  return hours.map((h, i) => ({ h, "정가 유지": Math.round(u0 * sBase[i]), "다이나믹": Math.round(ur * sDisc[i]) }));
}
function forecastData(it) {
  const wk = ["4주전", "3주전", "2주전", "1주전", "금주(예측)"];
  const avg = it.stock * it.base;
  const mul = [0.9, 1.08, 0.96, 1.1, 1.0];
  return wk.map((w, i) => ({ w, 실적: i <= 3 ? Math.round(avg * mul[i]) : null, 예측: i >= 3 ? Math.round(avg * mul[i]) : null }));
}

function hourFactor(min, profile) {
  const i = Math.max(0, Math.min(12, Math.floor((min - OPEN) / 60)));
  return profile[i] * profile.length;
}
function buildPath(zoneIdxs) {
  const pts = [{ x: 0.06, y: 0.9 }, { x: 0.06, y: 0.74 }];
  const ordered = [...zoneIdxs].sort((a, b) => ZONES[a].flow - ZONES[b].flow);
  ordered.forEach((zi) => {
    const acc = ZONES[zi].access;
    pts.push({ x: pts[pts.length - 1].x, y: acc.y });
    pts.push({ x: acc.x, y: acc.y, shop: true });
  });
  pts.push({ x: pts[pts.length - 1].x, y: 0.82 });
  pts.push({ x: 0.46, y: 0.84, pay: true });
  pts.push({ x: 0.04, y: 0.95 });
  return pts;
}
function spawnAgent(dz, pull) {
  const zoneIdxs = [];
  for (let i = 0; i < ZONES.length; i++) {
    let p = 0.28;
    if (i === 0 || i === 1) p += 0.15;
    if (dz.has(i)) p = Math.max(p, 0.4 + 0.45 * pull);  // 인하율 깊을수록(마감 임박) 유입↑
    if (rand() < p) zoneIdxs.push(i);
  }
  if (zoneIdxs.length === 0) zoneIdxs.push(Math.floor(rand() * ZONES.length));
  if (zoneIdxs.length > 4) zoneIdxs.length = 4;
  const party = rand() < 0.68 ? 1 : rand() < 0.85 ? 2 : 3;
  const household = Math.max(party, 1 + Math.floor(rand() * 4));
  const dealZones = zoneIdxs.filter((z) => dz.has(z));
  const budget = Math.round((16000 + rand() * 30000) * (1 + (household - 1) * 0.3));
  const basket = Math.round(budget * (0.55 + rand() * 0.32));
  const path = buildPath(zoneIdxs);
  return {
    x: path[0].x, y: path[0].y, ti: 1, dwell: 0, dir: 1, dead: false, counted: false,
    color: AGENT_COLORS[Math.floor(rand() * AGENT_COLORS.length)],
    party, dealZones, basket, purchased: rand() < 0.9, path,
  };
}

export default function Demo({ onGoToReport }) {
  const canvasRef = useRef(null);
  const ctrl = useRef({ paused: false, speed: 4, dz: new Set(), priced: {}, zoneLoss: {}, profileKey: "평일", heat: false });
  const [ui, setUi] = useState({ min: OPEN, visitors: 0, revenue: 0, live: 0, dealSales: 0, saved: 0 });
  const [paused, setPaused] = useState(false);
  const [speed, setSpeed] = useState(4);
  const [dayKey, setDayKey] = useState("평일");
  const [heatOn, setHeatOn] = useState(false);
  const [bleuOk, setBleuOk] = useState(true);

  const [queue, setQueue] = useState(() => [makeAlert(POOL[0]), makeAlert(POOL[3])]);
  const [processed, setProcessed] = useState(0);
  const [chosenRate, setChosenRate] = useState(bestRate(POOL[0]));
  const [pricedList, setPricedList] = useState([]);   // 다이나믹 프라이싱 적용 품목
  const [approveFx, setApproveFx] = useState(null);
  const current = queue[0] || null;

  useEffect(() => {
    const t = setInterval(() => {
      setQueue((q) => {
        if (q.length >= 4) return q;
        const a = pickAlert(q, ctrl.current.dz);
        return a ? [...q, a] : q;
      });
    }, 5000);
    return () => clearInterval(t);
  }, []);

  const rec = useMemo(() => (current ? bestRate(current) : 0), [current?.uid]);
  useEffect(() => { setChosenRate(rec); }, [current?.uid, rec]);

  function setSpeedBoth(s) { ctrl.current.speed = s; setSpeed(s); }
  function togglePause() { ctrl.current.paused = !ctrl.current.paused; setPaused(ctrl.current.paused); }
  function setDay(k) { ctrl.current.profileKey = k; setDayKey(k); }
  function toggleHeat() { ctrl.current.heat = !ctrl.current.heat; setHeatOn(ctrl.current.heat); }
  function apply() {
    if (!current) return;
    const it = current, cap = chosenRate;
    ctrl.current.dz.add(it.zi);
    ctrl.current.priced[it.zi] = cap;
    ctrl.current.zoneLoss[it.zi] = Math.round(costOf(it) * 0.9);
    setProcessed((p) => p + 1);
    setPricedList((l) => [...l, { name: it.name, zi: it.zi, weight: it.weight, price0: it.price, cap, uid: it.uid }]);
    setApproveFx({ name: it.name, cap, saved: savedWon(it, cap) });
    setQueue((q) => q.slice(1));
    setTimeout(() => setApproveFx(null), 2600);
  }
  function skip() { setQueue((q) => (q.length > 1 ? [...q.slice(1), q[0]] : q)); }
  function resetAll() {
    ctrl.current.dz = new Set(); ctrl.current.priced = {}; ctrl.current.zoneLoss = {};
    setProcessed(0); setApproveFx(null); setPricedList([]);
    setQueue([makeAlert(POOL[0]), makeAlert(POOL[3])]);
  }

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const sim = { min: OPEN, agents: [], spawnAcc: 0, visitors: 0, revenue: 0, dealSales: 0, saved: 0, pings: [], heat: new Float32Array(GW * GH) };
    let raf, last = performance.now(), lastPush = 0;

    function step(now) {
      const dtSec = Math.min(0.05, (now - last) / 1000);
      last = now;
      const c = ctrl.current;
      if (!c.paused) {
        const dtMin = c.speed * dtSec * SEC_TO_MIN;
        sim.min += dtMin;
        if (sim.min >= CLOSE) { sim.min = OPEN; sim.visitors = 0; sim.revenue = 0; }
        sim.spawnAcc += 0.6 * DAY_VOLUME[c.profileKey] * hourFactor(sim.min, PROFILES[c.profileKey]) * dtMin;
        const pull = fracOf(sim.min);
        while (sim.spawnAcc >= 1) {
          sim.spawnAcc -= 1;
          if (sim.agents.length < MAX_AGENTS) { sim.agents.push(spawnAgent(c.dz, pull)); sim.visitors++; }
        }
        for (let k = 0; k < sim.heat.length; k++) sim.heat[k] *= 0.985;
        for (const a of sim.agents) {
          const gi = Math.max(0, Math.min(GW - 1, Math.floor(a.x * GW)));
          const gj = Math.max(0, Math.min(GH - 1, Math.floor(a.y * GH)));
          sim.heat[gi + gj * GW] += dtSec * 1.5;
          if (a.dwell > 0) { a.dwell -= dtMin; continue; }
          const t = a.path[a.ti];
          const dx = t.x - a.x, dy = t.y - a.y, d = Math.hypot(dx, dy), st = WALK * dtMin;
          if (d <= st) {
            a.x = t.x; a.y = t.y;
            if (t.shop) a.dwell = 4 + rand() * 6;
            if (t.pay && !a.counted && a.purchased) {
              a.counted = true; sim.revenue += a.basket;
              for (const dzi of a.dealZones) {
                sim.dealSales++; sim.saved += (c.zoneLoss[dzi] || 8000);
                sim.pings.push({ x: ZONES[dzi].access.x, y: ZONES[dzi].access.y - 0.03, life: 1 });
              }
            }
            a.ti++;
            if (a.ti >= a.path.length) a.dead = true;
          } else { a.x += (dx / d) * st; a.y += (dy / d) * st; a.dir = dx < 0 ? -1 : 1; }
        }
        sim.agents = sim.agents.filter((a) => !a.dead);
        for (const p of sim.pings) p.life -= dtSec * 1.4;
        sim.pings = sim.pings.filter((p) => p.life > 0);
      }
      draw(ctx, sim, ctrl.current);
      if (now - lastPush > 160) {
        lastPush = now;
        setUi({ min: sim.min, visitors: sim.visitors, revenue: sim.revenue, live: sim.agents.length, dealSales: sim.dealSales, saved: sim.saved });
      }
      raf = requestAnimationFrame(step);
    }
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, []);

  const clock = `${String(Math.floor(ui.min / 60)).padStart(2, "0")}:${String(Math.floor(ui.min % 60)).padStart(2, "0")}`;
  const dayProg = Math.max(0, Math.min(1, (ui.min - OPEN) / (CLOSE - OPEN)));

  // ESL: 다이나믹 적용 품목의 실시간 가격 (없으면 대기 중 품목의 정상가)
  const shown = pricedList.length ? pricedList[pricedList.length - 1] : null;
  const eslItem = shown || current;
  const liveRate = shown ? curRate(ui.min, shown.cap) : 0;
  const livePrice = shown ? round10(shown.price0 * (1 - liveRate / 100)) : null;

  return (
    <div className="space-y-5">
      <style>{`
        @keyframes ffpulse { 0%,100%{opacity:.55} 50%{opacity:1} }
        @keyframes ffrec { 0%,100%{opacity:.3} 50%{opacity:1} }
        @keyframes ffalert { 0%,100%{box-shadow:0 0 0 0 rgba(230,0,45,.45)} 50%{box-shadow:0 0 0 6px rgba(230,0,45,0)} }
        @keyframes ffpop { 0%{transform:translate(-50%,8px) scale(.9);opacity:0} 45%{transform:translate(-50%,0) scale(1.04);opacity:1} 100%{transform:translate(-50%,0) scale(1);opacity:1} }
        @keyframes ffflash { 0%,100%{box-shadow:0 0 0 0 rgba(52,211,153,0)} 50%{box-shadow:0 0 0 4px rgba(52,211,153,.5)} }
      `}</style>

      {/* ── ① 매장 디지털 트윈 ── */}
      <Panel title="🛰️ 매장 디지털 트윈 · AI 다이나믹 프라이싱 시뮬레이션"
             right={<span className="text-xs text-slate-400">FreshWatch Live · 3D 뷰</span>}>
        <div className="relative w-full overflow-hidden rounded-2xl border-4 border-slate-800 bg-slate-950 shadow-xl ring-1 ring-black/30" style={{ aspectRatio: "1000 / 563" }}>
          <canvas ref={canvasRef} width={W} height={H} className="absolute inset-0 h-full w-full" />
          {/* 내부 비네트 — 모니터 느낌 */}
          <div className="pointer-events-none absolute inset-0" style={{ boxShadow: "inset 0 0 90px rgba(0,0,0,.55)" }} />

          {/* HUD 상단 */}
          <div className="absolute inset-x-0 top-0 z-10 flex items-center justify-between gap-3 bg-gradient-to-b from-[#0b1a22]/95 to-transparent px-4 py-2.5">
            <div className="flex items-center gap-3">
              <span className="flex items-center gap-1.5 text-sm font-extrabold tracking-wide text-emerald-300"><Store size={16} /> FRESHWATCH LIVE</span>
              <span className="hidden items-center gap-1.5 rounded-md bg-black/40 px-2 py-1 text-[11px] font-semibold text-red-400 sm:flex">
                <span className="h-1.5 w-1.5 rounded-full bg-red-500" style={{ animation: "ffrec 1.2s infinite" }} /> REC · CAM 01
              </span>
            </div>
            <div className="flex items-center gap-2">
              <span className="rounded-lg bg-black/45 px-3 py-1.5 font-mono text-base font-bold text-white tabular-nums">{clock}</span>
              <button onClick={togglePause} className="flex h-8 w-8 items-center justify-center rounded-lg bg-white/90 text-slate-800 hover:bg-white">
                {paused ? <Play size={15} fill="currentColor" /> : <Pause size={15} fill="currentColor" />}
              </button>
              <div className="flex overflow-hidden rounded-lg border border-white/20">
                {[1, 2, 4, 8].map((s) => (
                  <button key={s} onClick={() => setSpeedBoth(s)}
                    className={`px-2.5 py-1.5 text-xs font-bold ${speed === s ? "bg-emerald-400 text-slate-900" : "bg-black/40 text-slate-200 hover:bg-black/60"}`}>{s}×</button>
                ))}
              </div>
            </div>
          </div>

          {/* HUD 보조: 요일 프리셋 + 히트맵 */}
          <div className="absolute left-3 top-14 z-10 flex flex-wrap items-center gap-2">
            <div className="flex overflow-hidden rounded-lg border border-white/20">
              {["평일", "금요일", "주말"].map((k) => (
                <button key={k} onClick={() => setDay(k)}
                  className={`px-2.5 py-1 text-[11px] font-bold ${dayKey === k ? "bg-white text-slate-900" : "bg-black/45 text-slate-200 hover:bg-black/60"}`}>{k}</button>
              ))}
            </div>
            <button onClick={toggleHeat}
              className={`flex items-center gap-1 rounded-lg px-2.5 py-1 text-[11px] font-bold ${heatOn ? "bg-orange-400 text-slate-900" : "bg-black/45 text-slate-200 hover:bg-black/60"}`}>
              <Flame size={12} /> 동선 히트맵
            </button>
          </div>

          {/* 승인 토스트 */}
          {approveFx && (
            <div className="pointer-events-none absolute left-1/2 top-16 z-20" style={{ animation: "ffpop .4s ease-out" }}>
              <div className="flex items-center gap-2 rounded-2xl bg-emerald-500 px-4 py-2.5 text-sm font-extrabold text-white shadow-2xl ring-2 ring-emerald-300/50">
                <CheckCircle2 size={16} /> {approveFx.name} 다이나믹 적용 · 마감까지 최대 {approveFx.cap}% 자동 인하
              </div>
            </div>
          )}

          {/* 우측 KPI */}
          <div className="absolute right-3 top-16 z-10 w-[22%] min-w-[150px] space-y-2">
            <KpiCard icon={Users} label="누적 방문" value={`${ui.visitors.toLocaleString()}`} unit="세대" />
            <KpiCard icon={TrendingUp} label="신선 매출" value={wonShort(ui.revenue)} unit="원" accent />
            <KpiCard icon={Store} label="현재 체류" value={`${ui.live}`} unit="세대" />
            <KpiCard icon={Zap} label="폐기손실 방지" value={processed ? wonShort(ui.saved) : "0"} unit="원" hot={processed > 0} flash={!!approveFx}
              sub={`다이나믹 판매 ${ui.dealSales.toLocaleString()}건 · 적용 ${processed}품목`} />
            <div className="rounded-lg bg-black/45 p-2">
              <div className="mb-1 flex justify-between text-[10px] font-semibold text-slate-300"><span>영업 진행</span><span>{Math.round(dayProg * 100)}%</span></div>
              <div className="h-1.5 overflow-hidden rounded-full bg-white/15"><div className="h-full rounded-full bg-emerald-400" style={{ width: `${dayProg * 100}%` }} /></div>
            </div>
          </div>

          {/* 좌하단: 블리 폐기위험 감지 + ESL 실시간 가격 */}
          <div className="absolute bottom-3 left-3 z-10 flex items-end gap-3">
            <div className="w-[300px] rounded-2xl border bg-[#0b1a22]/94 p-3.5 shadow-2xl backdrop-blur"
                 style={current ? { borderColor: "rgba(230,0,45,.55)", animation: "ffalert 1.6s infinite" } : { borderColor: "rgba(52,211,153,.4)" }}>
              <div className="flex items-center gap-3">
                <span className="flex h-12 w-12 shrink-0 items-center justify-center overflow-hidden rounded-full bg-emerald-400/15 ring-1 ring-emerald-300/40">
                  {bleuOk ? <img src={`${BASE}bleu.png`} alt="블리" className="h-full w-full object-cover object-top" onError={() => setBleuOk(false)} /> : <span className="text-2xl">🧑‍🌾</span>}
                </span>
                <div className="min-w-0 flex-1 leading-tight">
                  <p className="text-sm font-extrabold text-emerald-300">AI 어시스턴트 · 블리</p>
                  {current ? (
                    <p className="mt-0.5 flex items-center gap-1 text-xs font-bold text-red-300"><AlertTriangle size={13} /> 폐기위험 {queue.length}건 감지</p>
                  ) : (
                    <p className="mt-0.5 flex items-center gap-1 text-xs font-bold text-emerald-300"><CheckCircle2 size={13} /> 감지 없음 · 전체 조치</p>
                  )}
                </div>
              </div>

              {current ? (
                <>
                  <div className="mt-3 rounded-lg bg-black/35 p-3 text-[13px] leading-relaxed text-slate-100">
                    <span className="mr-1 text-base">{current.emoji}</span>
                    <b className="text-white">{current.name}</b> <span className="text-slate-400">{current.weight}</span>
                    <span className="ml-1 rounded bg-red-500/80 px-1.5 py-0.5 text-[10px] font-bold text-white">D-{current.dday}</span>
                    <br />재고 {current.stock}팩 · 정가 방치 시 폐기손실 <b className="text-red-300">{wonShort(savedWon(current, rec))}원</b>
                    <br />AI 권장: <b className="text-emerald-300">다이나믹 프라이싱</b> (마감까지 최대 {rec}% 자동 인하)
                  </div>
                  <div className="mt-2.5 flex gap-2">
                    <button onClick={apply} className="flex flex-[2] items-center justify-center gap-1.5 rounded-xl bg-emerald-400 py-2.5 text-sm font-extrabold text-slate-900 hover:bg-emerald-300">
                      <Clock size={15} /> 다이나믹 적용 (최대 {chosenRate}%)
                    </button>
                    <button onClick={skip} title="다음으로 미루기" className="flex flex-1 items-center justify-center gap-1 rounded-xl border border-white/15 bg-white/5 py-2.5 text-xs font-bold text-slate-200 hover:bg-white/10">
                      <SkipForward size={13} /> 보류
                    </button>
                  </div>
                </>
              ) : (
                <div className="mt-3 flex gap-2">
                  <button onClick={resetAll} className="flex flex-1 items-center justify-center gap-1 rounded-xl border border-white/15 bg-white/5 py-2.5 text-xs font-bold text-slate-200 hover:bg-white/10"><RotateCcw size={13} /> 초기화</button>
                  {onGoToReport && <button onClick={onGoToReport} className="flex flex-1 items-center justify-center gap-1 rounded-xl bg-emerald-400 py-2.5 text-xs font-extrabold text-slate-900 hover:bg-emerald-300">성과 리포트 →</button>}
                </div>
              )}
            </div>

            {/* ESL — 다이나믹 프라이싱 실시간 가격(시간 따라 자동 인하) */}
            {eslItem && (
              <div className="relative hidden w-[184px] rounded-lg border border-slate-300 bg-slate-100 p-1.5 shadow-2xl md:block">
                <span className={`absolute right-1.5 -top-2 rounded-full px-2 py-0.5 text-[9px] font-extrabold text-white shadow ${shown ? "bg-brand-600" : "bg-slate-500"}`}
                      style={shown ? { animation: "ffpulse 1.2s infinite" } : undefined}>
                  {shown ? `다이나믹 ▼${liveRate}%` : "정상가"}
                </span>
                <div className="rounded-md bg-white px-2.5 py-2">
                  <p className="text-[11px] font-bold text-slate-900">{eslItem.name}</p>
                  <p className="text-[9px] text-slate-400">{ZONES[eslItem.zi].label} · {eslItem.weight} · ESL A-03</p>
                  {shown ? (
                    <div className="mt-1 flex items-end justify-end gap-1.5">
                      <span className="text-[10px] text-slate-400 line-through">₩{won(shown.price0)}</span>
                      <span className="text-xl font-extrabold text-brand-600 tabular-nums">₩{won(livePrice)}</span>
                    </div>
                  ) : (
                    <p className="mt-1 text-right text-xl font-extrabold text-slate-800 tabular-nums">₩{won(eslItem.price)}</p>
                  )}
                  {shown && <p className="mt-0.5 text-right text-[9px] font-semibold text-emerald-600">{clock} 기준 · 마감까지 자동 인하</p>}
                  <BarStrip />
                </div>
              </div>
            )}
          </div>
        </div>
        <p className="mt-4 text-[11px] leading-relaxed text-slate-400">
          ※ 승인 시 <b>고정 할인이 아니라 다이나믹 프라이싱</b>이 적용됩니다 — 유통기한·재고·수요에 따라 마감(22시)까지 가격이 <b>단계적으로 자동 인하</b>되며,
          ESL·매대 라벨의 가격이 시간에 따라 실시간으로 바뀝니다(배속을 올리면 뚜렷이 보입니다). 좌상단에서 요일·히트맵도 볼 수 있습니다.
        </p>
      </Panel>

      {/* ── ②③④ AI 다이나믹 프라이싱 근거 ── */}
      {current ? (
        <Panel title={`🧠 AI 다이나믹 프라이싱 근거 · ${current.name}`} right={<span className="text-xs text-slate-400">순이익 최대화 · 상한 40%</span>}>
          <div className="grid gap-5 lg:grid-cols-2">
            {/* 순이익 곡선(근거) */}
            <div>
              <p className="mb-2 text-xs font-semibold text-slate-500">최대 인하율별 기대 순이익 — 최고점이 AI 권장 마감가</p>
              <div className="h-52">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={profitCurve(current)} margin={{ top: 8, right: 14, left: -6, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
                    <XAxis dataKey="rate" tickLine={false} axisLine={false} tick={{ fontSize: 11, fill: "#94a3b8" }} unit="%" interval={4} />
                    <YAxis tickLine={false} axisLine={false} tick={{ fontSize: 11, fill: "#94a3b8" }} tickFormatter={(v) => wonShort(v)} />
                    <Tooltip contentStyle={CHART.tip} formatter={(v) => [`${won(v)}원`, "기대 순이익"]} labelFormatter={(l) => `최대 ${l}% 인하`} />
                    <ReferenceLine x={rec} stroke="#10b981" strokeWidth={2} label={{ value: `권장 ${rec}%`, position: "top", fontSize: 10, fill: "#059669" }} />
                    <ReferenceLine x={chosenRate} stroke="#3b82f6" strokeDasharray="4 4" label={{ value: "선택", position: "insideTopRight", fontSize: 10, fill: "#2563eb" }} />
                    <ReferenceLine y={0} stroke="#cbd5e1" />
                    <Line type="monotone" dataKey="net" stroke="#E6002D" strokeWidth={2.5} dot={{ r: 2 }} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              <p className="mt-1 text-[11px] leading-relaxed text-slate-400">방치하면 폐기 손실이 크고, 너무 깊으면 마진이 사라집니다. 두 힘의 <b>순이익 최고점</b>을 마감가로 권장합니다.</p>
            </div>

            {/* What-if + 가격 경로 */}
            <div>
              <div className="mb-3 flex items-center justify-between">
                <p className="text-xs font-semibold text-slate-500">최대 인하율 조정 (마감가 기준)</p>
                <span className="rounded-lg bg-brand-50 px-2.5 py-1 text-sm font-extrabold text-brand-600">{chosenRate}%</span>
              </div>
              <input type="range" min={0} max={40} step={1} value={chosenRate} onChange={(e) => setChosenRate(Number(e.target.value))} className="w-full accent-brand-600" />
              <div className="mt-3 grid grid-cols-3 gap-2">
                <MiniStat label="예상 판매" value={`${it_units(current, chosenRate)}팩`} tone="plain" />
                <MiniStat label="폐기 방지" value={`${wonShort(savedWon(current, chosenRate))}원`} tone="ok" />
                <MiniStat label="기대 순이익" value={`${wonShort(netProfit(current, chosenRate))}원`} tone={netProfit(current, chosenRate) >= netProfit(current, 0) ? "ok" : "danger"} />
              </div>
              <p className="mb-1 mt-3 text-xs font-semibold text-slate-500">시간대별 자동 인하 가격 경로</p>
              <div className="h-32">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={pricePath(current, chosenRate)} margin={{ top: 6, right: 12, left: 2, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
                    <XAxis dataKey="h" tickLine={false} axisLine={false} tick={{ fontSize: 10, fill: "#94a3b8" }} />
                    <YAxis tickLine={false} axisLine={false} tick={{ fontSize: 10, fill: "#94a3b8" }} tickFormatter={(v) => wonShort(v)} domain={["dataMin", "dataMax"]} />
                    <Tooltip contentStyle={CHART.tip} formatter={(v) => [`₩${won(v)}`, "판매가"]} />
                    <Line type="stepAfter" dataKey="가격" stroke="#E6002D" strokeWidth={2.5} dot={{ r: 2 }} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              <p className="mt-1 text-[11px] text-slate-400">아침엔 정상가, 마감이 가까울수록 <b>{chosenRate}%</b>까지 단계적으로 내려갑니다. ESL이 이 경로대로 실시간 반영됩니다.</p>
            </div>
          </div>

          {/* 수요예측 근거 + 판매량 비교 */}
          <div className="mt-5 grid gap-5 border-t border-slate-100 pt-4 lg:grid-cols-2">
            <div>
              <p className="mb-2 text-xs font-semibold text-slate-500">📊 수요예측 근거 — 최근 4주 실적 + 금주 예측</p>
              <div className="h-28">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={forecastData(current)} margin={{ top: 6, right: 12, left: -18, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
                    <XAxis dataKey="w" tickLine={false} axisLine={false} tick={{ fontSize: 10, fill: "#94a3b8" }} />
                    <YAxis tickLine={false} axisLine={false} tick={{ fontSize: 10, fill: "#94a3b8" }} />
                    <Tooltip contentStyle={CHART.tip} formatter={(v, n) => [`${v}팩`, n]} />
                    <Line type="monotone" dataKey="실적" stroke="#64748b" strokeWidth={2} dot={{ r: 2 }} />
                    <Line type="monotone" dataKey="예측" stroke="#E6002D" strokeWidth={2.5} strokeDasharray="5 4" dot={{ r: 3 }} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              <p className="mt-1 text-[11px] leading-relaxed text-slate-400">최근 4주 평균 소진율 <b>{Math.round(current.base * 100)}%</b> 기반으로 금주 재고 <b>{current.stock}팩</b>의 폐기위험을 예측합니다.</p>
            </div>
            <div>
              <p className="mb-2 text-xs font-semibold text-slate-500">📈 판매량 비교 — 정가 유지 vs 다이나믹</p>
              <div className="h-28">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={salesCurve(current, chosenRate)} margin={{ top: 6, right: 10, left: -18, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
                    <XAxis dataKey="h" tickLine={false} axisLine={false} tick={{ fontSize: 10, fill: "#94a3b8" }} />
                    <YAxis tickLine={false} axisLine={false} tick={{ fontSize: 10, fill: "#94a3b8" }} />
                    <Tooltip contentStyle={CHART.tip} formatter={(v, n) => [`${v}팩`, n]} />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                    <Line type="monotone" dataKey="정가 유지" stroke="#94a3b8" strokeWidth={2} strokeDasharray="5 4" dot={false} />
                    <Line type="monotone" dataKey="다이나믹" stroke="#E6002D" strokeWidth={2.5} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              <p className="mt-1 text-[11px] leading-relaxed text-slate-400">두 곡선의 간격이 곧 폐기 손실 방지 효과입니다.</p>
            </div>
          </div>
        </Panel>
      ) : (
        <Panel title="🧠 AI 다이나믹 프라이싱 근거">
          <p className="py-8 text-center text-sm text-slate-400">현재 감지된 폐기위험이 없습니다. 새 알림이 발생하면 근거·가격 경로·What-if가 여기에 표시됩니다.</p>
        </Panel>
      )}

      {/* ── ⑤ 도입 ROI 계산기 ── */}
      <RoiCalculator />
    </div>
  );
}

/* 숫자 카운트업 */
function useCountUp(target, ms = 550) {
  const [n, setN] = useState(target);
  const prev = useRef(target);
  useEffect(() => {
    const from = prev.current; let raf, st;
    const tick = (t) => {
      if (!st) st = t;
      const p = Math.min(1, (t - st) / ms), e = 1 - Math.pow(1 - p, 3);
      setN(from + (target - from) * e);
      if (p < 1) raf = requestAnimationFrame(tick); else prev.current = target;
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, ms]);
  return n;
}
function CountNum({ value, fmt }) {
  const n = useCountUp(value);
  return <>{fmt ? fmt(n) : Math.round(n).toLocaleString("ko-KR")}</>;
}

/* ============ ROI 계산기 ============ */
function RoiCalculator() {
  const [stores, setStores] = useState(120);
  const [rev, setRev] = useState(45);
  const [wasteNow, setWasteNow] = useState(4.9);
  const [wasteTgt, setWasteTgt] = useState(3.1);
  const feePerStore = 60;

  const perStoreSave = rev * 1e8 * (Math.max(0, wasteNow - wasteTgt) / 100);
  const annualSave = perStoreSave * stores;
  const annualFee = feePerStore * 1e4 * 12 * stores;
  const roiX = annualFee > 0 ? annualSave / annualFee : 0;
  const paybackMonths = perStoreSave > 0 ? (feePerStore * 1e4 * 12) / perStoreSave * 12 : 0;

  return (
    <Panel title="💰 도입 ROI 계산기" right={<span className="text-xs text-slate-400">가정 · 구독 {feePerStore}만원/점포·월</span>}>
      <div className="grid gap-6 lg:grid-cols-2">
        <div className="space-y-4">
          <RoiRow label="도입 점포 수" val={stores} unit="개" min={1} max={1000} step={1} on={setStores} />
          <RoiRow label="점포당 신선 연매출" val={rev} unit="억원" min={10} max={120} step={1} on={setRev} />
          <RoiRow label="현재 폐기율" val={wasteNow} unit="%" min={2} max={8} step={0.1} on={setWasteNow} />
          <RoiRow label="목표 폐기율" val={wasteTgt} unit="%" min={1} max={wasteNow} step={0.1} on={setWasteTgt} />
          <p className="text-[11px] leading-relaxed text-slate-400">
            절감액 = 점포 수 × 점포당 신선매출 × (현재−목표 폐기율). 다이나믹 프라이싱 폐기 −20.8%(Sanders 2024) 범위 내 가정값입니다.
          </p>
        </div>
        <div className="grid grid-cols-2 gap-3 self-start">
          <BigStat label="연간 폐기 절감액" value={<><CountNum value={annualSave} fmt={wonShort} />원</>} tone="ok" span />
          <BigStat label="연간 구독 비용" value={<><CountNum value={annualFee} fmt={wonShort} />원</>} />
          <BigStat label="ROI 배수" value={<><CountNum value={roiX} fmt={(v) => v.toFixed(1)} />×</>} tone="ok" />
          <BigStat label="투자 회수" value={paybackMonths < 1 ? "1개월 내" : `${Math.round(paybackMonths)}개월`} />
          <BigStat label="점포당 연 절감" value={<><CountNum value={perStoreSave} fmt={wonShort} />원</>} span />
        </div>
      </div>
    </Panel>
  );
}

function RoiRow({ label, val, unit, min, max, step, on }) {
  return (
    <div>
      <div className="mb-1 flex items-center justify-between text-xs">
        <span className="text-slate-500">{label}</span>
        <span className="font-bold text-slate-800">{val}{unit}</span>
      </div>
      <input type="range" min={min} max={max} step={step} value={val} onChange={(e) => on(Number(e.target.value))} className="w-full accent-brand-600" />
    </div>
  );
}

function BigStat({ label, value, tone = "plain", span }) {
  const t = tone === "ok" ? "text-emerald-600" : "text-slate-900";
  return (
    <div className={`rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3.5 ${span ? "col-span-2" : ""}`}>
      <p className="text-xs text-slate-500">{label}</p>
      <p className={`mt-1 text-2xl font-extrabold tracking-tight ${t}`}>{value}</p>
    </div>
  );
}

function MiniStat({ label, value, tone = "plain" }) {
  const t = tone === "danger" ? "text-brand-600" : tone === "ok" ? "text-emerald-600" : "text-slate-700";
  return (
    <div className="rounded-xl bg-slate-50 px-3 py-2.5 text-center">
      <p className="text-[11px] text-slate-500">{label}</p>
      <p className={`mt-0.5 text-sm font-bold ${t}`}>{value}</p>
    </div>
  );
}

function BarStrip() {
  return (
    <div className="mt-1.5 flex items-center gap-1.5 border-t border-dashed border-slate-200 pt-1">
      <div className="flex h-2.5 items-end gap-[1px]">
        {[2, 1, 3, 1, 2, 2, 1, 3, 1, 2, 1, 2].map((bw, i) => (<span key={i} style={{ width: bw }} className="h-full bg-slate-700" />))}
      </div>
      <span className="font-mono text-[6px] text-slate-300">8801234567890</span>
    </div>
  );
}

function KpiCard({ icon: Icon, label, value, unit, accent, hot, sub, flash }) {
  return (
    <div className={`rounded-lg border p-2.5 backdrop-blur ${hot ? "border-emerald-400/50 bg-emerald-500/15" : "border-white/10 bg-black/45"}`}
         style={flash ? { animation: "ffflash 1.3s ease-out" } : undefined}>
      <p className={`flex items-center gap-1 text-[10px] font-semibold ${hot ? "text-emerald-300" : "text-slate-400"}`}>{Icon && <Icon size={11} />} {label}</p>
      <p className={`mt-0.5 text-lg font-extrabold leading-none tabular-nums ${accent || hot ? "text-emerald-300" : "text-white"}`}>
        {value}<span className="ml-0.5 text-[10px] font-bold text-slate-400">{unit}</span>
      </p>
      {sub && <p className="mt-1 text-[9px] text-slate-400">{sub}</p>}
    </div>
  );
}

/* ============ 아이소메트릭 렌더링 ============ */
const GW = 16, GH = 11, TW = 32, TH = 16, OX = 420, OY = 92;
const isoW = (wx, wy, z = 0) => [OX + (wx - wy) * TW, OY + (wx + wy) * TH - z];
const iso = (nx, ny, z = 0) => isoW(nx * GW, ny * GH, z);

function fillPoly(ctx, pts, color) {
  ctx.beginPath(); ctx.moveTo(pts[0][0], pts[0][1]);
  for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0], pts[i][1]);
  ctx.closePath(); ctx.fillStyle = color; ctx.fill();
}
function isoBox(ctx, wx, wy, wd, wh, bh, top, left, right) {
  const tBk = isoW(wx, wy, bh), tBr = isoW(wx + wd, wy, bh), tFr = isoW(wx + wd, wy + wh, bh), tBl = isoW(wx, wy + wh, bh);
  const gBr = isoW(wx + wd, wy, 0), gFr = isoW(wx + wd, wy + wh, 0), gBl = isoW(wx, wy + wh, 0);
  fillPoly(ctx, [tBl, tFr, gFr, gBl], left);
  fillPoly(ctx, [tBr, tFr, gFr, gBr], right);
  fillPoly(ctx, [tBk, tBr, tFr, tBl], top);
  return { tBk, tBr, tFr, tBl };
}
function shade(hex, f) {
  const n = parseInt(hex.slice(1), 16);
  let r = (n >> 16) & 255, g = (n >> 8) & 255, b = n & 255;
  r = Math.min(255, Math.round(r * f)); g = Math.min(255, Math.round(g * f)); b = Math.min(255, Math.round(b * f));
  return `rgb(${r},${g},${b})`;
}
function heatColor(t) {
  t = Math.max(0, Math.min(1, t));
  const stops = [[59, 130, 246], [16, 185, 129], [250, 204, 21], [239, 68, 68]];
  const seg = Math.min(2, Math.floor(t * 3)), f = t * 3 - seg;
  const a = stops[seg], b = stops[seg + 1];
  const r = Math.round(a[0] + (b[0] - a[0]) * f), g = Math.round(a[1] + (b[1] - a[1]) * f), bl = Math.round(a[2] + (b[2] - a[2]) * f);
  return `rgba(${r},${g},${bl},${0.12 + 0.5 * t})`;
}
function timeOverlay(min) {
  const p = fracOf(min);
  if (p < 0.25) return `rgba(96,132,180,${((0.25 - p) / 0.25) * 0.10})`;   // 아침 쿨톤
  if (p < 0.55) return null;                                               // 한낮 중립
  if (p < 0.78) return `rgba(232,150,60,${((p - 0.55) / 0.23) * 0.15})`;   // 저녁 웜톤
  return `rgba(24,32,72,${0.10 + ((p - 0.78) / 0.22) * 0.24})`;            // 마감 임박 어스름
}
function draw(ctx, sim, c) {
  const bg = ctx.createLinearGradient(0, 0, 0, H);
  bg.addColorStop(0, "#0e1a24"); bg.addColorStop(1, "#080d12");
  ctx.fillStyle = bg; ctx.fillRect(0, 0, W, H);
  for (let i = 0; i < GW; i++) for (let j = 0; j < GH; j++) {
    const a = isoW(i, j), b = isoW(i + 1, j), d = isoW(i + 1, j + 1), e = isoW(i, j + 1);
    fillPoly(ctx, [a, b, d, e], (i + j) % 2 ? "#c8c5b8" : "#bfbcae");
  }
  if (c.heat) {
    for (let i = 0; i < GW; i++) for (let j = 0; j < GH; j++) {
      const t = sim.heat[i + j * GW] / 2.5;
      if (t > 0.05) {
        const a = isoW(i, j), b = isoW(i + 1, j), d = isoW(i + 1, j + 1), e = isoW(i, j + 1);
        fillPoly(ctx, [a, b, d, e], heatColor(t));
      }
    }
  }
  const c0 = isoW(0, 0), c1 = isoW(GW, 0), c2 = isoW(GW, GH), c3 = isoW(0, GH);
  ctx.strokeStyle = "rgba(80,124,114,0.55)"; ctx.lineWidth = 3;
  ctx.beginPath(); ctx.moveTo(c0[0], c0[1]); ctx.lineTo(c1[0], c1[1]); ctx.lineTo(c2[0], c2[1]); ctx.lineTo(c3[0], c3[1]); ctx.closePath(); ctx.stroke();

  const eMat = [iso(0.03, 0.86), iso(0.15, 0.86), iso(0.15, 0.98), iso(0.03, 0.98)];
  fillPoly(ctx, eMat, "#d7a64b");
  const emc = iso(0.09, 0.92);
  ctx.fillStyle = "#203239"; ctx.font = "bold 10px sans-serif"; ctx.textAlign = "center"; ctx.fillText("ENTRANCE", emc[0], emc[1] + 3);

  const items = [];
  ZONES.forEach((z, zi) => items.push({ key: (z.x + z.w / 2) * GW + (z.y + z.h) * GH, kind: "zone", z, zi }));
  for (let i = 0; i < 3; i++) { const nx = 0.30 + i * 0.10, ny = 0.80; items.push({ key: nx * GW + ny * GH, kind: "pos", nx, ny, i }); }
  for (const a of sim.agents) items.push({ key: a.x * GW + a.y * GH, kind: "agent", a });
  items.sort((p, q) => p.key - q.key);
  for (const it of items) {
    if (it.kind === "zone") drawZoneIso(ctx, it.z, it.zi, c, sim.min);
    else if (it.kind === "pos") drawPos(ctx, it.nx, it.ny, it.i);
    else drawShopper(ctx, it.a);
  }
  for (const p of sim.pings) {
    const s = iso(p.x, p.y, 40 + (1 - p.life) * 26);
    ctx.globalAlpha = Math.max(0, p.life);
    ctx.fillStyle = "#ffffff"; ctx.font = "bold 13px sans-serif"; ctx.textAlign = "center"; ctx.fillText("+판매", s[0], s[1]);
    ctx.globalAlpha = 1;
  }
  // 시간대별 조명 틴트
  const tint = timeOverlay(sim.min);
  if (tint) { ctx.fillStyle = tint; ctx.fillRect(0, 0, W, H); }
  // CCTV 스캔라인
  ctx.fillStyle = "rgba(20,50,60,0.04)";
  for (let y = 0; y < H; y += 4) ctx.fillRect(0, y, W, 1);
}
function drawZoneIso(ctx, z, zi, c, min) {
  const wx = z.x * GW, wy = z.y * GH, wd = z.w * GW, wh = z.h * GH;
  const cold = z.kind === "cold", wood = z.kind === "wood";
  const baseC = cold ? "#7fb0bd" : wood ? "#a9814f" : "#b09067";
  const bh = cold ? 30 : 26;
  const hot = c.dz.has(zi);
  const md = hot ? curRate(min, c.priced[zi] || 0) : 0;

  // 할인 적용 매대 글로우(은은한 펄스)
  if (hot) {
    const gc = isoW(wx + wd / 2, wy + wh + 0.5, 0);
    const pulse = 0.28 + 0.12 * Math.sin(Date.now() / 320);
    const rg = ctx.createRadialGradient(gc[0], gc[1], 3, gc[0], gc[1], 74);
    rg.addColorStop(0, `rgba(255,90,90,${pulse})`);
    rg.addColorStop(1, "rgba(255,90,90,0)");
    ctx.fillStyle = rg;
    ctx.beginPath(); ctx.ellipse(gc[0], gc[1], 74, 38, 0, 0, Math.PI * 2); ctx.fill();
  }

  const sBk = isoW(wx, wy), sBr = isoW(wx + wd, wy), sFr = isoW(wx + wd, wy + wh), sBl = isoW(wx, wy + wh);
  ctx.globalAlpha = 0.18; fillPoly(ctx, [sBk, sBr, sFr, sBl], "#000"); ctx.globalAlpha = 1;
  const top = isoBox(ctx, wx, wy, wd, wh, bh, shade(baseC, 1.12), shade(baseC, 0.72), shade(baseC, 0.9));

  const cols = 6, rows = 2, m = 0.16;
  for (let r = 0; r < rows; r++) for (let col = 0; col < cols; col++) {
    const pxw = wx + wd * (m + (col + 0.5) / cols * (1 - 2 * m));
    const pyw = wy + wh * (0.42 + (r + 0.5) / rows * 0.5);
    const s = isoW(pxw, pyw, bh + 2);
    ctx.fillStyle = z.dot[(r + col) % z.dot.length]; ctx.fillRect(s[0] - 4, s[1] - 4, 8, 6);
  }
  if (cold) { const g0 = isoW(wx, wy + wh, bh), g1 = isoW(wx + wd, wy + wh, bh); ctx.strokeStyle = "#bff0f4"; ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(g0[0], g0[1]); ctx.lineTo(g1[0], g1[1]); ctx.stroke(); }

  const lc = isoW(wx + wd / 2, wy + wh * 0.16, bh + 3);
  ctx.fillStyle = hot ? "#ffdede" : "#12303a"; ctx.font = "bold 11px sans-serif"; ctx.textAlign = "center"; ctx.fillText(z.label, lc[0], lc[1]);

  const pc = isoW(wx + wd / 2, wy + wh + 0.1, 14);
  ctx.textAlign = "center"; ctx.font = "bold 9px sans-serif"; ctx.fillStyle = "#eef5f2";
  ctx.fillText(hot ? (md > 0 ? `▼${md}%` : "다이나믹") : z.price.toLocaleString() + "원", pc[0], pc[1]);

  if (hot) {
    ctx.strokeStyle = "#ff4d4d"; ctx.lineWidth = 2.5;
    ctx.beginPath(); ctx.moveTo(top.tBk[0], top.tBk[1]); ctx.lineTo(top.tBr[0], top.tBr[1]); ctx.lineTo(top.tFr[0], top.tFr[1]); ctx.lineTo(top.tBl[0], top.tBl[1]); ctx.closePath(); ctx.stroke();
    const bc = isoW(wx + wd / 2, wy + wh / 2, bh + 20);
    ctx.fillStyle = "#ff4d4d"; ctx.beginPath(); ctx.arc(bc[0], bc[1], 13, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = "#fff"; ctx.font = "bold 9px sans-serif"; ctx.fillText(md > 0 ? md + "%" : "AI", bc[0], bc[1] + 3.5);
  }
}
function drawPos(ctx, nx, ny, i) {
  const wx = nx * GW, wy = ny * GH;
  isoBox(ctx, wx, wy, 1.0, 0.8, 18, "#4a6670", "#2c454e", "#3b555e");
  const t = isoW(wx + 0.5, wy + 0.9, 22), led = isoW(wx + 0.5, wy + 0.4, 30);
  ctx.fillStyle = "#efc654"; ctx.fillRect(led[0] - 2, led[1] - 8, 4, 8);
  ctx.fillStyle = "#dfeae7"; ctx.font = "bold 8px sans-serif"; ctx.textAlign = "center"; ctx.fillText("POS " + (i + 1), t[0], t[1]);
}
function drawShopper(ctx, a) {
  const [x, y] = iso(a.x, a.y, 0);
  ctx.fillStyle = "rgba(19,35,43,0.30)"; ctx.beginPath(); ctx.ellipse(x, y, 8, 4, 0, 0, Math.PI * 2); ctx.fill();
  const by = y - 4;
  ctx.fillStyle = "#8ea5ad"; ctx.fillRect(x + a.dir * 8 - 3, by - 6, 6, 5);
  ctx.fillStyle = a.color; ctx.fillRect(x - 4, by - 12, 8, 11);
  ctx.fillStyle = shade(a.color, 0.8); ctx.fillRect(x - 4, by - 12, 3, 11);
  ctx.fillStyle = "#f1c7a5"; ctx.beginPath(); ctx.arc(x, by - 15, 3.6, 0, Math.PI * 2); ctx.fill();
  ctx.fillStyle = "#30251f"; ctx.beginPath(); ctx.arc(x, by - 16.5, 3.6, Math.PI, Math.PI * 2); ctx.fill();
  if (a.party >= 2) { ctx.fillStyle = "#62b6a8"; ctx.fillRect(x - 10, by - 8, 5, 8); ctx.fillStyle = "#f1c7a5"; ctx.beginPath(); ctx.arc(x - 7.5, by - 10, 2.4, 0, Math.PI * 2); ctx.fill(); }
  if (a.party >= 3) { ctx.fillStyle = "#7a8ed2"; ctx.fillRect(x + 6, by - 6, 4, 6); ctx.fillStyle = "#f1c7a5"; ctx.beginPath(); ctx.arc(x + 8, by - 8, 2, 0, Math.PI * 2); ctx.fill(); }
}
