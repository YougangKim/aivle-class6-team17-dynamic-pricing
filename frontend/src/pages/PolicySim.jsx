import { useState, useMemo } from "react";
import { SlidersHorizontal, Wallet, Leaf, TrendingUp, AlertTriangle, Save } from "lucide-react";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, ReferenceDot, ReferenceLine } from "recharts";
import { Panel, Button } from "../components/ui";
import { simulatePolicy } from "../lib/api";
import { man } from "../lib/format";

const tip = { borderRadius: 12, border: "1px solid #cbd5e1", fontSize: 12, boxShadow: "0 4px 14px rgba(0,0,0,.10)", background: "#ffffff", color: "#0f172a" };

function Slider({ label, desc, value, onChange, min, max, step = 1, unit, marks }) {
  return (
    <div className="border-b border-slate-100 py-4 last:border-0">
      <div className="flex items-baseline justify-between">
        <div>
          <p className="text-sm font-semibold">{label}</p>
          {desc && <p className="mt-0.5 text-xs text-slate-400">{desc}</p>}
        </div>
        <span className="text-2xl font-bold tracking-tight">{value}<span className="ml-0.5 text-sm">{unit}</span></span>
      </div>
      <input type="range" min={min} max={max} step={step} value={value}
             onChange={(e) => onChange(+e.target.value)}
             className="mt-3 h-2 w-full cursor-pointer appearance-none rounded-full bg-slate-200 accent-brand-600" />
      {marks && (
        <div className="mt-1 flex justify-between text-[11px] text-slate-400">
          {marks.map((m) => <span key={m}>{m}</span>)}
        </div>
      )}
    </div>
  );
}

export default function PolicySim({ onToast }) {
  const [maxDiscount, setMax] = useState(40);
  const [startDay, setStart] = useState(2);
  const [autoApprove, setAuto] = useState(0);
  const [stores, setStores] = useState(110);

  const now = useMemo(() => simulatePolicy({ maxDiscount, startDay, autoApprove, stores }), [maxDiscount, startDay, autoApprove, stores]);
  const current = useMemo(() => simulatePolicy({ maxDiscount: 40, startDay: 2, autoApprove: 0, stores }), [stores]);

  const curve = useMemo(
    () => Array.from({ length: 13 }, (_, i) => {
      const rate = 20 + i * 5;
      const r = simulatePolicy({ maxDiscount: rate, startDay, autoApprove, stores });
      return { rate, net: Math.round(r.netTotal / 100000000), saved: Math.round(r.savedPerStore / 10000) };
    }),
    [startDay, autoApprove, stores]
  );
  const best = curve.reduce((a, b) => (b.net > a.net ? b : a), curve[0]);
  const delta = now.netTotal - current.netTotal;

  return (
    <div className="space-y-6">
      <div className="flex items-start gap-2.5 rounded-2xl border border-slate-200 bg-white px-5 py-3.5">
        <SlidersHorizontal size={15} className="mt-0.5 shrink-0 text-brand-600" />
        <p className="text-xs leading-relaxed text-slate-600">
          본사가 할인 정책을 바꿨을 때 <b>전 점포의 폐기·이익이 어떻게 달라지는지</b> 시뮬레이션합니다.
          점포당 연 폐기 84.5톤 · 처리단가 147,000원/톤 · 신선 마진율 19.7% 기준이며, 값은 추정치입니다.
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-5">
        <Panel className="lg:col-span-2" title="정책 변수">
          <Slider label="할인율 상한" desc="현행 본사 지침 40%" value={maxDiscount} onChange={setMax}
                  min={20} max={70} step={5} unit="%" marks={["20%", "40%", "70%"]} />
          <Slider label="할인 시작 시점" desc="유통기한 며칠 전부터 할인" value={startDay} onChange={setStart}
                  min={1} max={4} unit="일 전" marks={["1일", "2일", "3일", "4일"]} />
          <Slider label="자동 승인 임계값" desc="이 할인율 이하는 승인 없이 반영 (0 = 사용 안 함)" value={autoApprove} onChange={setAuto}
                  min={0} max={30} step={5} unit="%" marks={["미사용", "15%", "30%"]} />
          <Slider label="적용 점포 수" value={stores} onChange={setStores} min={4} max={110} step={1} unit="개점"
                  marks={["4", "30", "110"]} />
          <div className="mt-4 flex gap-2">
            <Button onClick={() => { setMax(40); setStart(2); setAuto(0); }}>현행 정책으로</Button>
            <Button variant="primary" onClick={() => onToast({ title: "정책안 저장됨", desc: `상한 ${maxDiscount}% · ${startDay}일 전 시작 · ${stores}개점` })}>
              <Save size={14} /> 정책안 저장
            </Button>
          </div>
        </Panel>

        <div className="space-y-4 lg:col-span-3">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="rounded-2xl border border-emerald-100 bg-emerald-50 p-5">
              <div className="flex items-center justify-between">
                <p className="text-xs font-medium text-emerald-700">전사 순효과 (연간)</p>
                <Wallet size={16} className="text-emerald-300" />
              </div>
              <p className="mt-2 text-3xl font-bold tracking-tight text-emerald-700">
                {(now.netTotal / 100000000).toFixed(1)}<span className="ml-1 text-sm">억원</span>
              </p>
              <p className={`mt-1 text-xs font-semibold ${delta >= 0 ? "text-emerald-600" : "text-brand-600"}`}>
                현행 대비 {delta >= 0 ? "+" : ""}{(delta / 100000000).toFixed(2)}억원
              </p>
            </div>
            <div className="rounded-2xl border border-slate-200 bg-white p-5">
              <div className="flex items-center justify-between">
                <p className="text-xs font-medium text-slate-500">폐기 감축률</p>
                <TrendingUp size={16} className="text-slate-200" />
              </div>
              <p className="mt-2 text-3xl font-bold tracking-tight">
                {Math.round(now.wasteReduction * 100)}<span className="ml-1 text-sm">%</span>
              </p>
              <p className="mt-1 text-xs text-slate-400">점포당 84.5톤 → {now.wasteTon}톤</p>
            </div>
          </div>

          <Panel title="상한별 전사 순효과" right={<span className="text-[11px] text-slate-400">현재 설정 기준 곡선</span>}>
            <div className="h-56">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={curve} margin={{ top: 10, right: 12, left: -18, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" strokeOpacity={0.5} />
                  <XAxis dataKey="rate" tickLine={false} axisLine={false} tick={{ fontSize: 11, fill: "#8b95a5" }} tickFormatter={(v) => `${v}%`} />
                  <YAxis tickLine={false} axisLine={false} tick={{ fontSize: 11, fill: "#8b95a5" }} tickFormatter={(v) => `${v}억`} />
                  <Tooltip contentStyle={tip} formatter={(v) => [`${v}억원`, "전사 순효과"]} labelFormatter={(l) => `할인 상한 ${l}%`} />
                  <ReferenceLine y={0} stroke="#cbd5e1" strokeDasharray="4 4" />
                  <Line type="monotone" dataKey="net" stroke="#E4002B" strokeWidth={2.6} dot={false} activeDot={{ r: 5 }} />
                  <ReferenceDot x={best.rate} y={best.net} r={6} fill="#E4002B" stroke="white" strokeWidth={2} />
                  <ReferenceDot x={maxDiscount} y={curve.find((c) => c.rate === maxDiscount)?.net ?? 0} r={5} fill="#0f172a" stroke="white" strokeWidth={2} />
                </LineChart>
              </ResponsiveContainer>
            </div>
            <div className="mt-2 flex flex-wrap gap-4 text-[11px] text-slate-500">
              <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-brand-600" /> 최적 상한 {best.rate}%</span>
              <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-slate-900" /> 현재 선택 {maxDiscount}%</span>
            </div>
          </Panel>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <div className="rounded-2xl border border-slate-200 bg-white p-5">
          <p className="text-xs font-medium text-slate-500">점포당 폐기 절감액</p>
          <p className="mt-1.5 text-xl font-bold">{man(now.savedPerStore)}만원</p>
        </div>
        <div className="rounded-2xl border border-slate-200 bg-white p-5">
          <p className="text-xs font-medium text-slate-500">점포당 마진 훼손</p>
          <p className="mt-1.5 text-xl font-bold text-brand-600">−{man(now.marginLossPerStore)}만원</p>
        </div>
        <div className="rounded-2xl border border-emerald-100 bg-emerald-50 p-5">
          <div className="flex items-center gap-1.5">
            <Leaf size={13} className="text-emerald-600" />
            <p className="text-xs font-medium text-emerald-700">점포당 탄소 감축</p>
          </div>
          <p className="mt-1.5 text-xl font-bold text-emerald-700">{now.co2eTon} tCO₂e</p>
        </div>
      </div>

      {maxDiscount > 50 && (
        <div className="flex items-start gap-2.5 rounded-2xl border border-brand-100 bg-brand-50 px-5 py-3.5">
          <AlertTriangle size={15} className="mt-0.5 shrink-0 text-brand-600" />
          <p className="text-xs leading-relaxed text-brand-700">
            할인 상한 50% 초과 구간은 <b>현장 인터뷰에서 확인된 리스크</b>가 있습니다.
            원가 이하 판매 가능성과 정가 구매 고객의 이탈(할인 대기 고객군 형성)이 보고되었습니다. 실제 적용 전 검증이 필요합니다.
          </p>
        </div>
      )}
    </div>
  );
}
