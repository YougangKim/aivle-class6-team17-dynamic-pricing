import { Wallet, TrendingDown, Check } from "lucide-react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Cell, PieChart, Pie } from "recharts";
import { Panel, Kpi, Skeleton, ErrorBox, useAsync } from "../components/ui";
import { getKpi } from "../lib/api";
import { man, pct } from "../lib/format";

const tooltipStyle = { borderRadius: 12, border: "1px solid #cbd5e1", fontSize: 12, boxShadow: "0 4px 14px rgba(0,0,0,.10)", background: "#ffffff", color: "#0f172a" };
const PIE = ["#E6002D", "#f59e0b", "#cbd5e1"];

export default function Performance({ storeId, approvedCount = 0 }) {
  const { data, loading, error, reload } = useAsync(() => getKpi(storeId), [storeId]);
  if (error) return <ErrorBox message={error} onRetry={reload} />;

  return (
    <div className="space-y-6">
      <div className="grid gap-4 md:grid-cols-3">
        <Kpi loading={loading} index={0} tone="ok" label="이번 달 폐기 절감" value={data && man(data.saved_amount)} unit="만원"
             sub={data && `전월 대비 +${pct(data.saved_delta)}%`} icon={Wallet} />
        <Kpi loading={loading} index={1} label="폐기율" value={data && (data.waste_rate * 100).toFixed(1)} unit="%"
             sub={data && `도입 전 ${(data.waste_rate_before * 100).toFixed(1)}% → 현재 ${(data.waste_rate * 100).toFixed(1)}%`} icon={TrendingDown} />
        <Kpi loading={loading} index={2} label="추천 승인률" value={data && pct(data.approval_rate)} unit="%"
             sub="그대로 84% · 조정 7% · 반려 9%" icon={Check} />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Panel className="lg:col-span-2" title="월별 폐기 손실액"
               right={<span className="text-xs font-semibold text-emerald-600">4개월 연속 감소</span>}>
          <div className="h-64">
            {loading ? <Skeleton className="h-full w-full" /> : (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={data.monthly} margin={{ top: 6, right: 6, left: -20, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" strokeOpacity={0.5} vertical={false} />
                  <XAxis dataKey="m" tickLine={false} axisLine={false} tick={{ fontSize: 12, fill: "#8b95a5" }} />
                  <YAxis tickLine={false} axisLine={false} tick={{ fontSize: 12, fill: "#8b95a5" }} />
                  <Tooltip cursor={{ fill: "#f8fafc" }} contentStyle={tooltipStyle} formatter={(v) => [`${v}만원`, "폐기 손실"]} />
                  <Bar dataKey="v" radius={[8, 8, 0, 0]} barSize={44}>
                    {data.monthly.map((_, i) => (
                      <Cell key={i} fill={i === data.monthly.length - 1 ? "#E6002D" : "#e2e8f0"} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>
        </Panel>

        <Panel title="추천 처리 비율">
          <div className="h-64">
            {loading ? <Skeleton className="h-full w-full" /> : (
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={data.approval_breakdown} dataKey="value" nameKey="name" innerRadius={52} outerRadius={80} paddingAngle={3} stroke="none">
                    {data.approval_breakdown.map((_, i) => <Cell key={i} fill={PIE[i]} />)}
                  </Pie>
                  <Tooltip contentStyle={tooltipStyle} formatter={(v, n) => [`${v}%`, n]} />
                </PieChart>
              </ResponsiveContainer>
            )}
          </div>
          {!loading && (
            <div className="space-y-1.5">
              {data.approval_breakdown.map((b, i) => (
                <div key={b.name} className="flex items-center gap-2 text-xs">
                  <span className="h-2 w-2 rounded-full" style={{ background: PIE[i] }} />
                  <span className="flex-1 text-slate-500">{b.name}</span>
                  <span className="font-semibold">{b.value}%</span>
                </div>
              ))}
            </div>
          )}
        </Panel>
      </div>

      <Panel title="미승인 건의 실제 결과"
             right={<span className="text-xs text-slate-400">서비스 효과 검증 지표</span>}>
        {loading ? <Skeleton className="h-24 w-full" /> : (
          <div className="grid gap-4 md:grid-cols-4">
            {[
              ["반려한 추천", `${data.rejected.count}건`, ""],
              ["그중 실제 폐기", `${data.rejected.wasted}건`, ""],
              ["발생 손실", `${man(data.rejected.loss)}만원`, "text-brand-600"],
              ["추천대로 했다면", `−${man(data.rejected.could_save)}만원`, "text-emerald-600"],
            ].map(([k, v, cls]) => (
              <div key={k} className="rounded-xl bg-slate-50 px-4 py-3">
                <p className="text-xs text-slate-500">{k}</p>
                <p className={`mt-1 text-xl font-bold ${cls}`}>{v}</p>
              </div>
            ))}
          </div>
        )}
      </Panel>
    </div>
  );
}
