import { Leaf, TreePine, Car, Home as HomeIcon, Target, Info } from "lucide-react";
import {
  AreaChart, Area, BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Cell, Legend,
} from "recharts";
import { Panel, Kpi, Skeleton, ErrorBox, useAsync } from "../components/ui";
import { getEsg, CARBON_FACTOR } from "../lib/api";

const tip = { borderRadius: 12, border: "1px solid #cbd5e1", fontSize: 12, boxShadow: "0 4px 14px rgba(0,0,0,.10)", background: "#ffffff", color: "#0f172a" };

export default function Esg({ scope = "store" }) {
  const { data, loading, error, reload } = useAsync(() => getEsg(scope), [scope]);
  if (error) return <ErrorBox message={error} onRetry={reload} />;
  const d = data;
  const progress = d ? Math.round((d.target.current / d.target.goal) * 100) : 0;

  return (
    <div className="space-y-6">
      <div className="flex items-start gap-2.5 rounded-2xl border border-emerald-100 bg-emerald-50 px-5 py-3.5">
        <Leaf size={15} className="mt-0.5 shrink-0 text-emerald-600" />
        <p className="text-xs leading-relaxed text-emerald-800">
          폐기 감축은 비용 절감인 동시에 <b>탄소 감축</b>입니다. 카테고리별 탄소계수(축산 27.0 · 수산 6.1 · 즉석 3.4 ·
          유제품 1.9 · 청과 0.9 kgCO₂e/kg)를 적용해 환산했습니다.
          <span className="ml-1 text-emerald-600">근거: Eriksson et al.(2015) 슈퍼마켓 식품폐기물 탄소발자국 연구</span>
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi loading={loading} index={0} tone="ok" label="감축 폐기물" value={d && (d.saved_waste_kg / 1000).toFixed(1)} unit="톤" icon={Leaf} sub="5개월 누적" />
        <Kpi loading={loading} index={1} tone="ok" label="탄소 감축" value={d && (d.saved_co2e_kg / 1000).toFixed(1)} unit="tCO₂e" icon={Leaf} sub="폐기 감축분 환산" />
        <Kpi loading={loading} index={2} label="탄소 집약도" value={d && (d.saved_co2e_kg / d.saved_waste_kg).toFixed(1)} unit="kgCO₂e/kg" icon={Leaf}
             sub="감축 폐기물 1kg당 탄소 감축량" />
        <Kpi loading={loading} index={3} label="감축목표 달성률" value={d && Math.round((d.target.current / d.target.goal) * 100)} unit="%" icon={Target}
             sub={d && `현재 ${Math.round(d.target.current * 100)}% / 목표 ${Math.round(d.target.goal * 100)}%`} />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Panel className="lg:col-span-2" title="월별 탄소 감축량"
               right={<span className="text-xs font-semibold text-emerald-600">누적 {d ? (d.saved_co2e_kg / 1000).toFixed(1) : "–"} tCO₂e</span>}>
          <div className="h-56">
            {loading ? <Skeleton className="h-full w-full" /> : (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={d.months} margin={{ top: 6, right: 6, left: -20, bottom: 0 }}>
                  <defs>
                    <linearGradient id="gCo2" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#059669" stopOpacity={0.28} />
                      <stop offset="100%" stopColor="#059669" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" strokeOpacity={0.5} vertical={false} />
                  <XAxis dataKey="m" tickLine={false} axisLine={false} tick={{ fontSize: 12, fill: "#8b95a5" }} />
                  <YAxis tickLine={false} axisLine={false} tick={{ fontSize: 12, fill: "#8b95a5" }} tickFormatter={(v) => `${v}t`} />
                  <Tooltip contentStyle={tip} formatter={(v, n) => [n === "co2e" ? `${v} tCO₂e` : `${v} 톤`, n === "co2e" ? "탄소 감축" : "폐기 감축"]} />
                  <Area type="monotone" dataKey="co2e" stroke="#059669" strokeWidth={2.4} fill="url(#gCo2)" />
                </AreaChart>
              </ResponsiveContainer>
            )}
          </div>
        </Panel>

        <Panel title="감축 목표 진행률">
          {loading ? <Skeleton className="h-56 w-full" /> : (
            <div className="flex h-56 flex-col justify-center">
              <div className="flex items-center gap-2">
                <Target size={15} className="text-brand-600" />
                <p className="text-sm font-semibold">{d.target.name}</p>
              </div>
              <div className="mt-5 flex items-baseline gap-2">
                <span className="text-4xl font-bold tracking-tight text-emerald-600">{Math.round(d.target.current * 100)}%</span>
                <span className="text-sm text-slate-400">/ 목표 {Math.round(d.target.goal * 100)}%</span>
              </div>
              <div className="mt-4 h-3 overflow-hidden rounded-full bg-slate-100">
                <div className="h-full rounded-full bg-emerald-500 transition-all duration-1000" style={{ width: `${progress}%` }} />
              </div>
              <p className="mt-2 text-xs text-slate-500">목표 달성률 <b className="text-slate-700">{progress}%</b></p>
              <p className="mt-4 rounded-xl bg-slate-50 px-3 py-2.5 text-[11px] leading-relaxed text-slate-500">
                고객사 지속가능경영보고서의 폐기 감축 목표와 연동해 관리합니다. 서비스 도입 성과가 ESG 공시 지표로 바로 활용됩니다.
              </p>
            </div>
          )}
        </Panel>
      </div>

      <Panel title="카테고리별 무게 vs 탄소 비중"
             right={<span className="text-[11px] text-slate-400">같은 1kg이라도 탄소는 다릅니다</span>}>
        <div className="h-64">
          {loading ? <Skeleton className="h-full w-full" /> : (
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={d.by_category} margin={{ top: 6, right: 10, left: -18, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" strokeOpacity={0.5} vertical={false} />
                <XAxis dataKey="name" tickLine={false} axisLine={false} tick={{ fontSize: 12, fill: "#8b95a5" }} />
                <YAxis tickLine={false} axisLine={false} tick={{ fontSize: 11, fill: "#8b95a5" }} tickFormatter={(v) => `${v}%`} />
                <Tooltip cursor={{ fill: "#f8fafc" }} contentStyle={tip} formatter={(v, n) => [`${v}%`, n === "waste_share" ? "폐기 무게 비중" : "탄소 비중"]} />
                <Legend iconType="circle" wrapperStyle={{ fontSize: 12 }}
                        formatter={(v) => (v === "waste_share" ? "폐기 무게 비중" : "탄소 비중")} />
                <Bar dataKey="waste_share" fill="#cbd5e1" radius={[6, 6, 0, 0]} barSize={22} />
                <Bar dataKey="co2_share" radius={[6, 6, 0, 0]} barSize={22}>
                  {d.by_category.map((c, i) => <Cell key={i} fill={c.name === "축산" ? "#E4002B" : "#059669"} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>
        <div className="mt-3 flex items-start gap-2 rounded-xl bg-brand-50 px-4 py-3">
          <Info size={13} className="mt-0.5 shrink-0 text-brand-600" />
          <p className="text-xs leading-relaxed text-brand-700">
            축산은 폐기 <b>무게의 21%</b>에 불과하지만 <b>탄소의 58%</b>를 차지합니다.
            축산 폐기를 우선 줄이는 것이 비용·탄소 양쪽에서 가장 효율적이라는 뜻이며, AI 추천 우선순위도 이 구조를 따릅니다.
          </p>
        </div>
      </Panel>

      <Panel title="환산 지표" right={<span className="text-[11px] text-slate-400">감축량을 체감 단위로 환산</span>}>
        {loading ? <Skeleton className="h-20 w-full" /> : (
          <div className="grid gap-4 sm:grid-cols-3">
            {[
              [TreePine, "소나무", `${d.equivalents.trees.toLocaleString()}그루`, "연간 CO₂ 흡수량 기준"],
              [Car, "승용차 주행", `${d.equivalents.car_km.toLocaleString()}km`, "중형 휘발유차 기준"],
              [HomeIcon, "가구 연간 배출", `${d.equivalents.households}가구`, "4인 가구 연간 탄소배출"],
            ].map(([Icon, label, value, desc]) => (
              <div key={label} className="rounded-2xl bg-emerald-50 px-4 py-4">
                <Icon size={18} className="text-emerald-600" />
                <p className="mt-2 text-xs font-medium text-emerald-700">{label}</p>
                <p className="mt-0.5 text-xl font-bold text-emerald-800">{value}</p>
                <p className="mt-1 text-[11px] text-emerald-600">{desc}</p>
              </div>
            ))}
          </div>
        )}
      </Panel>
    </div>
  );
}
