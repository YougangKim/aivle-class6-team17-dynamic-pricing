import { useState, useMemo } from "react";
import { X, Sparkles, TrendingUp, AlertTriangle, Check, Lock, Clock } from "lucide-react";
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, ReferenceDot, ReferenceLine,
  ReferenceArea, ComposedChart, Bar,
} from "recharts";
import { profitCurve, getForecast, pricePath, rateAt, DEFAULT_POLICY, ESL_MIN_DELTA } from "../lib/api";
import { won, man, discounted } from "../lib/format";
import { Skeleton, Button, DayTag, useAsync } from "./ui";

const axisWon = (value) => {
  const amount = Number(value || 0);
  const absolute = Math.abs(amount);
  if (absolute >= 10000) return `${Number((amount / 10000).toFixed(absolute < 100000 ? 1 : 0))}만`;
  if (absolute >= 1000) return `${Number((amount / 1000).toFixed(1))}천`;
  return `${Number(amount.toFixed(absolute < 10 ? 1 : 0))}원`;
};

const profitDomain = ([dataMin, dataMax]) => {
  const span = Math.max(dataMax - dataMin, Math.abs(dataMin) * 0.1, Math.abs(dataMax) * 0.1, 1);
  const padding = span * 0.12;
  return [Math.floor(dataMin - padding), Math.ceil(dataMax + padding)];
};

const hhmm = (m) => `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;

const tip = { borderRadius: 12, border: "1px solid #cbd5e1", fontSize: 12, boxShadow: "0 4px 14px rgba(0,0,0,.10)", background: "#ffffff", color: "#0f172a" };

export default function DetailModal({ item, rate, onRate, onClose, onApprove, onReject, canApprove, threshold, policy }) {
  /* 곡선은 본사 상한(40%)까지 전부 그리고, 정책 상한 밖은 회색으로 막아 표시합니다.
     "모델은 더 내리고 싶은데 정책이 막고 있다"를 눈으로 보여주기 위함입니다. */
  const cap = item.policy_cap ?? 40;
  const curve = useMemo(() => profitCurve(item, 40), [item]);

  /* 마감 가격 경로 — 승인하면 이 스케줄대로 자동 인하됩니다 */
  const p = policy ?? DEFAULT_POLICY;
  const closeMin = 22 * 60;
  const startMin = (p.closing_hour ?? 20) * 60;
  const path = useMemo(
    () => pricePath(item, { startMin, closeMin, cap, earliestMin: closeMin - 240 }),
    [item, startMin, closeMin, cap]
  );
  const pathData = useMemo(() => {
    if (path.flat) return [];
    const rows = [{ min: path.startMin, label: hhmm(path.startMin), 할인율: path.r0, esl: true }];
    path.steps.forEach((s) => rows.push({ min: s.min, label: hhmm(s.min), 할인율: s.rate, esl: s.esl }));
    return rows;
  }, [path]);
  const fc = useAsync(() => getForecast(item.product_id), [item.product_id]);
  const [hover, setHover] = useState(null);

  const best = curve.reduce((a, b) => (b.net > a.net ? b : a), curve[0]);
  const cur = curve.reduce((a, b) => (Math.abs(b.rate - rate) < Math.abs(a.rate - rate) ? b : a), curve[0]);
  const recRate = Math.round(item.recommended_rate * 100);
  const rec = curve.reduce((a, b) => (Math.abs(b.rate - recRate) < Math.abs(a.rate - recRate) ? b : a), curve[0]);
  const noAction = curve[0];
  const gain = cur.net - noAction.net;
  /* 담당자는 결재선 이하 건만 여기서 직접 반려할 수 있습니다 */
  const managerOnly = rate > threshold && !canApprove;

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
              <span className="text-xs text-slate-400">
                AI 추천 {recRate}% · 모델 최적 {best.rate}%
                {item.capped_by_policy && <span className="ml-1 font-semibold text-cjorange-600">(상한 {cap}%)</span>}
              </span>
            </div>

            <div className="mb-5 flex items-baseline gap-3">
              <span className="text-4xl font-bold tracking-tight">{rate}<span className="text-lg">%</span></span>
              <span className="text-sm text-slate-400 line-through">{won(item.regular_price)}원</span>
              <span className="text-xl font-bold">{won(discounted(item.regular_price, rate / 100))}원</span>
            </div>

            <input
              type="range" min="0" max={cap} step="1" value={Math.min(rate, cap)}
              onChange={(e) => onRate(+e.target.value)}
              className="h-2 w-full cursor-pointer appearance-none rounded-full bg-slate-200 accent-brand-600"
            />
            <div className="mt-1.5 flex justify-between text-[11px] text-slate-400">
              <span>0%</span>
              <span className="font-semibold text-slate-500">{threshold}% 결재선</span>
              <span className="font-semibold text-brand-600">{cap}% 상한</span>
            </div>
            {item.capped_by_policy && (
              <p className="mt-3 flex items-start gap-1.5 rounded-xl bg-cjorange-50 px-3 py-2 text-[11px] leading-relaxed text-cjorange-800">
                <Lock size={12} className="mt-px shrink-0" />
                <span>
                  잔여 {item.days_until_expiry}일 정책 상한 <b>{cap}%</b>가 적용 중입니다.
                  제약이 없다면 모델은 <b>{Math.round(item.uncapped_rate * 100)}%</b>를 권장하며,
                  그 경우 순이익이 <b>{man(item.uncapped_gain - (item.expected_gain ?? 0))}만원</b> 더 개선됩니다.
                </span>
              </p>
            )}
            {rate > threshold && (
              <p className="mt-3 flex items-center gap-1.5 rounded-xl bg-brand-50 px-3 py-2 text-[11px] font-medium text-brand-700">
                <Check size={12} /> {threshold}% 초과 할인입니다. 담당자 승인 후 <b>점장 최종 승인</b>을 거쳐 반영됩니다.
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
              판매 마진에서 잔여 재고의 원가 손실과 폐기 처리비를 뺀 값입니다(잔여일이 남은 재고는 이월 잔존가치를 반영).
              1%p 단위로 계산하며, 곡선의 정점이 순이익이 가장 큰 지점입니다.
            </p>
            <div className="h-56 rounded-2xl border border-slate-200 p-3">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={curve} margin={{ top: 10, right: 12, left: 4, bottom: 0 }}
                           onMouseMove={(s) => s?.activePayload && setHover(s.activePayload[0].payload)}
                           onMouseLeave={() => setHover(null)}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" strokeOpacity={0.5} />
                  <XAxis dataKey="rate" tickLine={false} axisLine={false} tick={{ fontSize: 11, fill: "#8b95a5" }} tickFormatter={(v) => `${v}%`} />
                  <YAxis domain={profitDomain} allowDecimals tickLine={false} axisLine={false} tick={{ fontSize: 11, fill: "#8b95a5" }} tickFormatter={axisWon} />
                  <Tooltip contentStyle={tip}
                           formatter={(v) => [axisWon(v), "기대 손익"]}
                           labelFormatter={(l) => `할인율 ${l}%`} />
                  <ReferenceLine y={0} stroke="#cbd5e1" strokeDasharray="4 4" />
                  {cap < 40 && <ReferenceArea x1={cap} x2={40} fill="#0f172a" fillOpacity={0.06}
                                              label={{ value: "정책 상한 밖", fontSize: 10, fill: "#94a3b8" }} />}
                  <ReferenceLine x={threshold} stroke="#94a3b8" strokeDasharray="3 3"
                                 label={{ value: `${threshold}% 결재선`, position: "insideTopRight", fontSize: 10, fill: "#94a3b8" }} />
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

          {/* 마감 가격 경로 */}
          <section>
            <h3 className="mb-1 flex items-center gap-1.5 text-sm font-semibold">
              <Clock size={14} className="text-cjorange-600" /> 마감까지 가격 경로
            </h3>
            {path.flat ? (
              <p className="rounded-2xl bg-slate-50 px-4 py-3 text-xs leading-relaxed text-slate-500">
                {path.reason === "잔여일 보유"
                  ? `잔여 ${item.days_until_expiry}일 상품이라 오늘 마감까지 소진할 필요가 없습니다. 승인한 ${Math.round(item.recommended_rate * 100)}%가 마감까지 유지되며, 내일 잔여일이 줄면 추천이 다시 계산됩니다.`
                  : `추천 할인율이 이미 상한 ${cap}%라 추가 인하 여지가 없습니다.`}
              </p>
            ) : (
              <>
                <p className="mb-3 text-xs leading-relaxed text-slate-500">
                  승인하면 <b className="text-slate-700">{hhmm(path.startMin)}</b>부터 <b className="text-slate-700">{hhmm(closeMin)}</b>까지{" "}
                  <b className="text-slate-700">{path.gapMin}분마다 {path.stepPp}%p</b>씩 자동으로 내려가
                  마감 시각에 <b className="text-brand-600">{path.target}%</b>에 도달합니다. 매번 승인할 필요가 없습니다.
                </p>
                <div className="h-44 rounded-2xl border border-slate-200 p-3">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={pathData} margin={{ top: 10, right: 14, left: -10, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" strokeOpacity={0.5} vertical={false} />
                      <XAxis dataKey="label" tickLine={false} axisLine={false} tick={{ fontSize: 10, fill: "#8b95a5" }} interval="preserveStartEnd" />
                      <YAxis tickLine={false} axisLine={false} tick={{ fontSize: 11, fill: "#8b95a5" }}
                             domain={[path.r0 - 1, path.target + 1]} tickFormatter={(v) => `${v}%`} />
                      <Tooltip contentStyle={tip}
                               formatter={(v, _n, pl) => [`${v}%  ·  ${won(discounted(item.regular_price, v / 100))}원${pl.payload.esl ? "  · ESL 전송" : ""}`, "할인율"]}
                               labelFormatter={(l) => `${l} 시점`} />
                      <ReferenceLine y={threshold} stroke="#94a3b8" strokeDasharray="3 3"
                                     label={{ value: `${threshold}% 결재선`, position: "insideBottomRight", fontSize: 10, fill: "#94a3b8" }} />
                      <Line type="stepAfter" dataKey="할인율" stroke="#F97316" strokeWidth={2.4}
                            dot={(d) => {
                              if (d?.cx == null || d?.cy == null) return null;
                              const sent = !!d.payload?.esl;
                              return (
                                <circle key={`d${d.index}`} cx={d.cx} cy={d.cy} r={sent ? 4 : 2.5}
                                        fill={sent ? "#F97316" : "#fed7aa"} stroke="white" strokeWidth={sent ? 1.5 : 1} />
                              );
                            }} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
                <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-slate-500">
                  <span className="flex items-center gap-1.5">
                    <span className="h-2.5 w-2.5 rounded-full bg-cjorange-500" /> ESL 전송 {path.eslCount}회
                  </span>
                  <span className="flex items-center gap-1.5">
                    <span className="h-2 w-2 rounded-full bg-cjorange-200" /> 내부 계산만 (전송 없음)
                  </span>
                  <span className="text-slate-400">
                    가격은 1%p 단위로 바뀌지만 ESL 전송은 직전 반영가 대비 {ESL_MIN_DELTA}%p 이상 벌어질 때만 합니다 — 라벨 배터리 보호
                  </span>
                </div>
              </>
            )}
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
            {onReject && (
              <Button onClick={onReject} disabled={managerOnly}
                      title={managerOnly ? "점장 승인 대상입니다 · 반려는 점장 계정에서 처리합니다" : "반려 사유를 남기면 AI가 새 할인율을 다시 계산합니다"}
                      className="border-brand-200 text-brand-600 hover:bg-brand-50">
                <X size={15} /> 반려
              </Button>
            )}
            <Button variant="primary" onClick={onApprove}><Check size={15} /> {rate > threshold ? "이 가격으로 결재 요청" : "이 가격으로 승인"}</Button>
          </div>
        </div>
      </div>
    </div>
  );
}
