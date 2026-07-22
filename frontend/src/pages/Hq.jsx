import { Building2, TrendingDown, Wallet, CheckCircle2, ArrowRight, MapPin } from "lucide-react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Cell, AreaChart, Area } from "recharts";
import { Panel, Kpi, Skeleton, ErrorBox, useAsync } from "../components/ui";
import { getHqOverview } from "../lib/api";
import { man, pct } from "../lib/format";

const tip = { borderRadius: 12, border: "1px solid #cbd5e1", fontSize: 12, boxShadow: "0 4px 14px rgba(0,0,0,.10)", background: "#ffffff", color: "#0f172a" };

export default function Hq({ onPickStore }) {
  const { data, loading, error, reload } = useAsync(() => getHqOverview(), []);
  if (error) return <ErrorBox message={error} onRetry={reload} />;
  const d = data;
  const ranked = d ? [...d.stores].sort((a, b) => a.waste_rate - b.waste_rate) : [];

  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi loading={loading} index={0} label="운영 점포" value={d?.total_stores} unit="개점" icon={Building2} sub="수도권 파일럿" />
        <Kpi loading={loading} index={1} tone="ok" label="누적 절감액" value={d && man(d.total_saved)} unit="만원" icon={Wallet} sub="5개월 누적" />
        <Kpi loading={loading} index={2} label="평균 폐기율" value={d && (d.avg_waste_rate * 100).toFixed(1)} unit="%" icon={TrendingDown} sub="도입 전 4.9%" />
        <Kpi loading={loading} index={3} label="추천 채택률" value={d && pct(d.adoption_rate)} unit="%" icon={CheckCircle2} sub="4개점 평균" />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Panel className="lg:col-span-2" title="점포별 폐기율" right={<span className="text-[11px] text-slate-400">낮을수록 우수</span>}>
          <div className="h-56">
            {loading ? <Skeleton className="h-full w-full" /> : (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={ranked.map((s) => ({ ...s, rate: +(s.waste_rate * 100).toFixed(1) }))}
                          margin={{ top: 6, right: 10, left: -18, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" strokeOpacity={0.5} vertical={false} />
                  <XAxis dataKey="name" tickLine={false} axisLine={false} tick={{ fontSize: 11, fill: "#8b95a5" }}
                         tickFormatter={(v) => v.replace("롯데마트 ", "")} />
                  <YAxis tickLine={false} axisLine={false} tick={{ fontSize: 11, fill: "#8b95a5" }} tickFormatter={(v) => `${v}%`} />
                  <Tooltip cursor={{ fill: "#f8fafc" }} contentStyle={tip} formatter={(v) => [`${v}%`, "폐기율"]} />
                  <Bar dataKey="rate" radius={[8, 8, 0, 0]} barSize={46}>
                    {ranked.map((s, i) => (
                      <Cell key={i} fill={s.waste_rate > 0.04 ? "#E4002B" : s.waste_rate > 0.033 ? "#F58220" : "#059669"} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>
        </Panel>

        <Panel title="전사 누적 절감액" right={<span className="text-xs font-semibold text-emerald-600">우상향</span>}>
          <div className="h-56">
            {loading ? <Skeleton className="h-full w-full" /> : (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={d.monthly_total} margin={{ top: 6, right: 6, left: -22, bottom: 0 }}>
                  <defs>
                    <linearGradient id="gHq" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#059669" stopOpacity={0.25} />
                      <stop offset="100%" stopColor="#059669" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" strokeOpacity={0.5} vertical={false} />
                  <XAxis dataKey="m" tickLine={false} axisLine={false} tick={{ fontSize: 11, fill: "#8b95a5" }} />
                  <YAxis tickLine={false} axisLine={false} tick={{ fontSize: 11, fill: "#8b95a5" }} tickFormatter={(v) => `${v}백만`} />
                  <Tooltip contentStyle={tip} formatter={(v) => [`${v}백만원`, "누적 절감"]} />
                  <Area type="monotone" dataKey="v" stroke="#059669" strokeWidth={2.2} fill="url(#gHq)" />
                </AreaChart>
              </ResponsiveContainer>
            )}
          </div>
        </Panel>
      </div>

      <Panel padded={false} title="점포 현황" right={<span className="text-[11px] text-slate-400">행을 클릭하면 해당 점포로 이동합니다</span>}>
        {loading ? (
          <div className="space-y-3 p-5">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-12 w-full" />)}</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-sm">
              <thead>
                <tr className="border-b border-slate-100 text-left text-xs text-slate-400">
                  <th className="px-5 py-3 font-medium">순위 · 점포</th>
                  <th className="px-3 py-3 font-medium">상권</th>
                  <th className="px-3 py-3 text-right font-medium">폐기율</th>
                  <th className="px-3 py-3 text-right font-medium">절감액</th>
                  <th className="px-3 py-3 text-right font-medium">채택률</th>
                  <th className="px-5 py-3 text-right font-medium">미처리</th>
                </tr>
              </thead>
              <tbody>
                {ranked.map((s, i) => (
                  <tr key={s.store_id} onClick={() => onPickStore(s.store_id)}
                      className="cursor-pointer border-b border-slate-50 transition-colors last:border-0 hover:bg-slate-50">
                    <td className="px-5 py-3.5">
                      <div className="flex items-center gap-2.5">
                        <span className={`flex h-6 w-6 items-center justify-center rounded-lg text-xs font-bold ${
                          i === 0 ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-500"
                        }`}>{i + 1}</span>
                        <span className="font-semibold">{s.name}</span>
                      </div>
                    </td>
                    <td className="px-3 py-3.5">
                      <span className="inline-flex items-center gap-1 rounded-md bg-slate-100 px-2 py-0.5 text-[11px] text-slate-500">
                        <MapPin size={10} /> {s.area}
                      </span>
                    </td>
                    <td className="px-3 py-3.5 text-right">
                      <span className={`font-bold ${s.waste_rate > 0.04 ? "text-brand-600" : "text-slate-900"}`}>
                        {(s.waste_rate * 100).toFixed(1)}%
                      </span>
                      <span className="ml-1.5 text-[11px] font-medium text-emerald-600">{s.trend}%p</span>
                    </td>
                    <td className="px-3 py-3.5 text-right font-semibold">{man(s.saved)}만원</td>
                    <td className="px-3 py-3.5 text-right text-slate-600">{pct(s.approval_rate)}%</td>
                    <td className="px-5 py-3.5 text-right">
                      <span className="rounded-lg bg-brand-50 px-2.5 py-1 text-xs font-bold text-brand-600">{s.pending}건</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <Panel title="확산 로드맵">
        {loading ? <Skeleton className="h-24 w-full" /> : (
          <div className="grid gap-3 md:grid-cols-3">
            {d.rollout.map((r, i) => {
              const style = {
                done: "border-emerald-200 bg-emerald-50",
                current: "border-brand-200 bg-brand-50",
                planned: "border-slate-200 bg-slate-50",
              }[r.status];
              const badge = {
                done: ["완료", "bg-emerald-600"],
                current: ["진행 중", "bg-brand-600"],
                planned: ["예정", "bg-slate-400"],
              }[r.status];
              return (
                <div key={r.phase} className={`relative rounded-2xl border px-4 py-4 ${style}`}>
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-bold">{r.phase}</span>
                    <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold text-white ${badge[1]}`}>{badge[0]}</span>
                  </div>
                  <p className="mt-2 text-2xl font-bold tracking-tight">{r.stores}<span className="ml-1 text-xs font-semibold">개점</span></p>
                  <p className="mt-1 text-xs text-slate-500">{r.desc}</p>
                  {i < d.rollout.length - 1 && (
                    <ArrowRight size={16} className="absolute -right-3 top-1/2 hidden -translate-y-1/2 text-slate-300 md:block" />
                  )}
                </div>
              );
            })}
          </div>
        )}
        <p className="mt-3 text-xs leading-relaxed text-slate-500">
          현재 절감액을 전국 110개점 기준으로 환산하면 연간 약 <b className="text-slate-700">13.6억원</b> 규모입니다.
          (점포당 연 폐기 84.5톤 · 처리단가 147,000원/톤 기준 추정)
        </p>
      </Panel>
    </div>
  );
}
