import { FlaskConical, TrendingDown, TrendingUp, CheckCircle2, BookOpen } from "lucide-react";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend } from "recharts";
import { Panel, Skeleton, ErrorBox, useAsync } from "../components/ui";
import { getAbTest } from "../lib/api";
import { pct } from "../lib/format";

const tip = { borderRadius: 12, border: "1px solid #cbd5e1", fontSize: 12, boxShadow: "0 4px 14px rgba(0,0,0,.10)", background: "#ffffff", color: "#0f172a" };

function Compare({ label, unit, treat, ctrl, better = "down" }) {
  const lift = ((treat - ctrl) / ctrl) * 100;
  const good = better === "down" ? lift < 0 : lift > 0;
  return (
    <div className="rounded-2xl border border-slate-200 p-4">
      <p className="text-xs font-medium text-slate-500">{label}</p>
      <div className="mt-3 space-y-2">
        <div className="flex items-center justify-between">
          <span className="flex items-center gap-1.5 text-xs text-brand-600">
            <span className="h-2 w-2 rounded-full bg-brand-600" /> 적용
          </span>
          <b className="text-lg font-bold text-brand-600">{treat}{unit}</b>
        </div>
        <div className="flex items-center justify-between">
          <span className="flex items-center gap-1.5 text-xs text-slate-400">
            <span className="h-2 w-2 rounded-full bg-slate-300" /> 대조
          </span>
          <b className="text-lg font-bold text-slate-400">{ctrl}{unit}</b>
        </div>
      </div>
      <div className={`mt-3 flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-xs font-bold ${
        good ? "bg-emerald-50 text-emerald-700" : "bg-brand-50 text-brand-600"
      }`}>
        {better === "down" ? <TrendingDown size={13} /> : <TrendingUp size={13} />}
        {lift > 0 ? "+" : ""}{lift.toFixed(1)}%
      </div>
    </div>
  );
}

export default function AbTest() {
  const { data, loading, error, reload } = useAsync(() => getAbTest(), []);
  if (error) return <ErrorBox message={error} onRetry={reload} />;
  const d = data;

  return (
    <div className="space-y-6">
      <div className="flex items-start gap-2.5 rounded-2xl border border-cjblue-100 bg-cjblue-50 px-5 py-3.5">
        <FlaskConical size={15} className="mt-0.5 shrink-0 text-cjblue-600" />
        <div className="text-xs leading-relaxed text-cjblue-800">
          <p><b>실험 설계</b> · {loading ? "…" : d.design}</p>
          <p className="mt-0.5 text-cjblue-600">{loading ? "" : `측정 기간 ${d.period}`}</p>
        </div>
      </div>

      {loading ? (
        <div className="grid gap-4 md:grid-cols-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-40 w-full" />)}</div>
      ) : (
        <div className="grid gap-4 md:grid-cols-3">
          <Compare label="폐기율" unit="%" treat={+(d.treatment.waste_rate * 100).toFixed(1)} ctrl={+(d.control.waste_rate * 100).toFixed(1)} better="down" />
          <Compare label="신선 마진율" unit="%" treat={+(d.treatment.margin_rate * 100).toFixed(1)} ctrl={+(d.control.margin_rate * 100).toFixed(1)} better="up" />
          <Compare label="임박품 판매전환율" unit="%" treat={+(d.treatment.conversion * 100).toFixed(0)} ctrl={+(d.control.conversion * 100).toFixed(0)} better="up" />
        </div>
      )}

      <Panel title="주차별 폐기율 추이" right={<span className="text-[11px] text-slate-400">낮을수록 우수</span>}>
        <div className="h-64">
          {loading ? <Skeleton className="h-full w-full" /> : (
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={d.weekly} margin={{ top: 6, right: 10, left: -20, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" strokeOpacity={0.5} vertical={false} />
                <XAxis dataKey="w" tickLine={false} axisLine={false} tick={{ fontSize: 11, fill: "#8b95a5" }} />
                <YAxis tickLine={false} axisLine={false} tick={{ fontSize: 11, fill: "#8b95a5" }} tickFormatter={(v) => `${v}%`} domain={[2, 5.4]} />
                <Tooltip contentStyle={tip} formatter={(v, n) => [`${v}%`, n === "적용" ? "적용 점포" : "대조 점포"]} />
                <Legend iconType="circle" wrapperStyle={{ fontSize: 12 }} formatter={(v) => (v === "적용" ? "적용 점포 (서울역·양평)" : "대조 점포 (잠실·청량리)")} />
                <Line type="monotone" dataKey="적용" stroke="#E4002B" strokeWidth={2.6} dot={{ r: 2.5 }} activeDot={{ r: 5 }} />
                <Line type="monotone" dataKey="대조" stroke="#cbd5e1" strokeWidth={2.4} strokeDasharray="5 4" dot={{ r: 2.5 }} />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>
      </Panel>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="통계적 유의성">
          {loading ? <Skeleton className="h-32 w-full" /> : (
            <div className="space-y-3">
              <div className="flex items-center justify-between rounded-xl bg-emerald-50 px-4 py-3">
                <div className="flex items-center gap-2">
                  <CheckCircle2 size={15} className="text-emerald-600" />
                  <span className="text-sm font-semibold text-emerald-800">유의미한 차이 확인</span>
                </div>
                <b className="text-sm text-emerald-700">p = {d.significance.p_value}</b>
              </div>
              <div className="space-y-2 text-xs">
                <div className="flex justify-between border-b border-slate-100 pb-2">
                  <span className="text-slate-500">폐기율 차이 95% 신뢰구간</span><b>{d.significance.ci}</b>
                </div>
                <div className="flex justify-between border-b border-slate-100 pb-2">
                  <span className="text-slate-500">관측 상품·일 수</span><b>{d.significance.n.toLocaleString()}건</b>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-500">폐기율 개선폭</span>
                  <b className="text-emerald-600">{pct(d.lift.waste)}%</b>
                </div>
              </div>
              <p className="rounded-xl bg-slate-50 px-3 py-2.5 text-[11px] leading-relaxed text-slate-500">
                상권·매출규모를 매칭한 2:2 비교이며, 계절성은 동일 기간 비교로 통제했습니다.
                점포 수가 적어 실제 도입 시에는 더 많은 표본으로 재검증이 필요합니다.
              </p>
            </div>
          )}
        </Panel>

        <Panel title="선행연구 대비">
          {loading ? <Skeleton className="h-32 w-full" /> : (
            <div className="space-y-3">
              <div className="flex items-start gap-2 rounded-xl bg-cjblue-50 px-4 py-3">
                <BookOpen size={14} className="mt-0.5 shrink-0 text-cjblue-600" />
                <p className="text-xs leading-relaxed text-cjblue-800">{d.benchmark}</p>
              </div>
              <div className="space-y-2.5">
                {[
                  ["폐기 감축", "−20.8%", `${pct(d.lift.waste)}%`],
                  ["이익 개선", "+2.9%", `+${pct(d.lift.margin)}%`],
                ].map(([k, paper, ours]) => (
                  <div key={k} className="rounded-xl border border-slate-200 px-4 py-3">
                    <p className="text-xs font-semibold">{k}</p>
                    <div className="mt-2 flex items-center justify-between text-xs">
                      <span className="text-slate-500">선행연구 {paper}</span>
                      <span className="rounded-lg bg-brand-50 px-2 py-1 font-bold text-brand-600">본 실험 {ours}</span>
                    </div>
                  </div>
                ))}
              </div>
              <p className="text-[11px] leading-relaxed text-slate-400">
                선행연구와 방향이 일치하며 폭은 더 큽니다. 대상 카테고리(신선 전반)와 할인 상한이 달라 직접 비교는 참고용입니다.
              </p>
            </div>
          )}
        </Panel>
      </div>
    </div>
  );
}
