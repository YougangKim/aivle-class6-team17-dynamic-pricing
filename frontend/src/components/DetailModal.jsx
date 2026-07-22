import { useState, useMemo } from "react";
import { X, Sparkles, TrendingUp, AlertTriangle, Check } from "lucide-react";
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, ReferenceDot, ReferenceLine,
  ComposedChart, Bar,
} from "recharts";
import { profitCurve, getForecast, APPROVAL_THRESHOLD } from "../lib/api";
import { won, man, discounted } from "../lib/format";
import { Skeleton, Button, DayTag, useAsync } from "./ui";

const tip = { borderRadius: 12, border: "1px solid #cbd5e1", fontSize: 12, boxShadow: "0 4px 14px rgba(0,0,0,.10)", background: "#ffffff", color: "#0f172a" };

export default function DetailModal({ item, rate, onRate, onClose, onApprove }) {
  const curve = useMemo(() => profitCurve(item), [item]);
  const fc = useAsync(() => getForecast(item.product_id), [item.product_id]);
  const [hover, setHover] = useState(null);

  const best = curve.reduce((a, b) => (b.net > a.net ? b : a), curve[0]);
  const cur = curve.reduce((a, b) => (Math.abs(b.rate - rate) < Math.abs(a.rate - rate) ? b : a), curve[0]);
  const recRate = Math.round(item.recommended_rate * 100);
  const rec = curve.reduce((a, b) => (Math.abs(b.rate - recRate) < Math.abs(a.rate - recRate) ? b : a), curve[0]);
  const noAction = curve[0];
  const gain = cur.net - noAction.net;

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-slate-900/50 p-0 backdrop-blur-sm sm:items-center sm:p-6" onClick={onClose}>
      <div
        className="animate-fade-up max-h-[92vh] w-full max-w-3xl overflow-y-auto rounded-t-3xl bg-white shadow-2xl sm:rounded-3xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* 헤더 */}
        <div className="sticky top-0 z-10 flex items-start justify-between border-b border-slate-100 bg-white/95 px-6 py-5 backdrop-blur">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-lg font-bold tracking-tight">{item.product_name}</h2>
              <DayTag d={item.days_until_expiry} />
              <span className="rounded-md bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-500">{item.category}</span>
            </div>
            <p className="mt-1 text-xs text-slate-500">
              재고 {item.stock_quantity}개 · 원가 {won(item.cost)}원 · 정가 {won(item.regular_price)}원
            </p>
          </div>
          <button onClick={onClose} className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-slate-100">
            <X size={18} />
          </button>
        </div>

        <div className="space-y-6 px-6 py-6">
          {/* 시뮬레이터 */}
          <section className="rounded-2xl border border-slate-200 p-5">
            <div className="mb-4 flex items-center justify-between">
              <h3 className="flex items-center gap-1.5 text-sm font-semibold">
                <Sparkles size={14} className="text-cjblue-600" /> 할인율 시뮬레이터
              </h3>
              <span className="text-xs text-slate-400">AI 추천 {recRate}% · 최적 {best.rate}%</span>
            </div>

            <div className="mb-5 flex items-baseline gap-3">
              <span className="text-4xl font-bold tracking-tight">{rate}<span className="text-lg">%</span></span>
              <span className="text-sm text-slate-400 line-through">{won(item.regular_price)}원</span>
              <span className="text-xl font-bold">{won(discounted(item.regular_price, rate / 100))}원</span>
            </div>

            <input
              type="range" min="0" max="40" step="1" value={rate}
              onChange={(e) => onRate(+e.target.value)}
              className="h-2 w-full cursor-pointer appearance-none rounded-full bg-slate-200 accent-brand-600"
            />
            <div className="mt-1.5 flex justify-between text-[11px] text-slate-400">
              <span>0%</span><span>10%</span><span>20%</span>
              <span className="font-semibold text-slate-500">30% 반응 시작</span>
              <span className="font-semibold text-brand-600">40% 상한</span>
            </div>
            {rate > APPROVAL_THRESHOLD && (
              <p className="mt-3 flex items-center gap-1.5 rounded-xl bg-brand-50 px-3 py-2 text-[11px] font-medium text-brand-700">
                <Check size={12} /> {APPROVAL_THRESHOLD}% 초과 할인입니다. 담당자 승인 후 <b>점장 최종 승인</b>을 거쳐 반영됩니다.
              </p>
            )}

            <div className="mt-5 grid gap-3 sm:grid-cols-3">
              {[
                ["예상 판매", `${cur.sold}개 / ${item.stock_quantity}개`, "text-slate-900"],
                ["판매 확률", `${cur.prob}%`, "text-slate-900"],
                ["미조치 대비", `${gain >= 0 ? "+" : ""}${man(gain)}만원`, gain >= 0 ? "text-emerald-600" : "text-brand-600"],
              ].map(([k, v, cls]) => (
                <div key={k} className="rounded-xl bg-slate-50 px-4 py-3">
                  <p className="text-[11px] text-slate-500">{k}</p>
                  <p className={`mt-0.5 text-base font-bold ${cls}`}>{v}</p>
                </div>
              ))}
            </div>
          </section>

          {/* 손익 곡선 */}
          <section>
            <h3 className="mb-1 flex items-center gap-1.5 text-sm font-semibold">
              <TrendingUp size={14} className="text-brand-600" /> 할인율별 기대 손익
            </h3>
            <p className="mb-3 text-xs text-slate-500">
              판매 마진에서 잔여 재고의 원가 손실과 폐기 처리비를 뺀 값입니다. 곡선의 정점이 순이익이 가장 큰 지점입니다.
            </p>
            <div className="h-56 rounded-2xl border border-slate-200 p-3">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={curve} margin={{ top: 10, right: 12, left: -8, bottom: 0 }}
                           onMouseMove={(s) => s?.activePayload && setHover(s.activePayload[0].payload)}
                           onMouseLeave={() => setHover(null)}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" strokeOpacity={0.5} />
                  <XAxis dataKey="rate" tickLine={false} axisLine={false} tick={{ fontSize: 11, fill: "#8b95a5" }} tickFormatter={(v) => `${v}%`} />
                  <YAxis tickLine={false} axisLine={false} tick={{ fontSize: 11, fill: "#8b95a5" }} tickFormatter={(v) => `${Math.round(v / 10000)}만`} />
                  <Tooltip contentStyle={tip}
                           formatter={(v) => [`${man(v)}만원`, "기대 손익"]}
                           labelFormatter={(l) => `할인율 ${l}%`} />
                  <ReferenceLine y={0} stroke="#cbd5e1" strokeDasharray="4 4" />
                  <Line type="monotone" dataKey="net" stroke="#E4002B" strokeWidth={2.5} dot={false} activeDot={{ r: 5 }} />
                  <ReferenceDot x={best.rate} y={best.net} r={6} fill="#E4002B" stroke="white" strokeWidth={2} />
                  <ReferenceDot x={cur.rate} y={cur.net} r={5} fill="#0f172a" stroke="white" strokeWidth={2} />
                </LineChart>
              </ResponsiveContainer>
            </div>
            <div className="mt-2 flex flex-wrap gap-4 text-[11px] text-slate-500">
              <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-brand-600" /> 최적점 {best.rate}% ({man(best.net)}만원)</span>
              <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-slate-900" /> 현재 선택 {cur.rate}% ({man(cur.net)}만원)</span>
              <span>미조치 시 {man(noAction.net)}만원</span>
            </div>
          </section>

          {/* 수요예측 */}
          <section>
            <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold">
              최근 판매량과 예측
              <span className="rounded-md bg-cjblue-50 px-2 py-0.5 text-[11px] font-semibold text-cjblue-700">AI 예측</span>
            </h3>
            <div className="h-44 rounded-2xl border border-slate-200 p-3">
              {fc.loading ? <Skeleton className="h-full w-full" /> : (
                <ResponsiveContainer width="100%" height="100%">
                  <ComposedChart data={fc.data} margin={{ top: 8, right: 12, left: -14, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" strokeOpacity={0.5} vertical={false} />
                    <XAxis dataKey="day" tickLine={false} axisLine={false} tick={{ fontSize: 11, fill: "#8b95a5" }} />
                    <YAxis tickLine={false} axisLine={false} tick={{ fontSize: 11, fill: "#8b95a5" }} />
                    <Tooltip contentStyle={tip} formatter={(v, n) => [`${v}개`, n]} />
                    <Bar dataKey="실제" fill="#cbd5e1" radius={[5, 5, 0, 0]} barSize={18} />
                    <Line type="monotone" dataKey="예측" stroke="#0072BC" strokeWidth={2.2} strokeDasharray="5 4" dot={{ r: 3, fill: "#0072BC" }} />
                  </ComposedChart>
                </ResponsiveContainer>
              )}
            </div>
          </section>

          {/* 근거 */}
          <section className="rounded-2xl bg-slate-50 p-4">
            <p className="text-xs font-semibold text-slate-700">AI 추천 근거</p>
            <p className="mt-1.5 text-xs leading-relaxed text-slate-600">{item.reason}</p>
            {!item.esl_applicable && (
              <p className="mt-2 flex items-center gap-1.5 text-xs font-medium text-violet-700">
                <AlertTriangle size={13} /> ESL 미적용 품목으로 승인 후 수기 라벨 부착이 필요합니다.
              </p>
            )}
          </section>
        </div>

        {/* 하단 */}
        <div className="sticky bottom-0 flex items-center justify-between gap-3 border-t border-slate-100 bg-white/95 px-6 py-4 backdrop-blur">
          <p className="text-xs text-slate-500">
            선택 <b className="text-slate-900">{rate}%</b>
            {rate !== recRate && <span className="ml-1.5 text-amber-600">· AI 추천 {recRate}%에서 조정됨</span>}
          </p>
          <div className="flex gap-2">
            <Button onClick={() => onRate(recRate)}>추천값으로 되돌리기</Button>
            <Button variant="primary" onClick={onApprove}><Check size={15} /> {rate > APPROVAL_THRESHOLD ? "이 가격으로 결재 요청" : "이 가격으로 승인"}</Button>
          </div>
        </div>
      </div>
    </div>
  );
}
