import { useState, useMemo } from "react";
import { Check, Minus, Plus, Loader2, TrendingUp, ShieldCheck, PackagePlus, Info } from "lucide-react";
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import { Panel, Kpi, Skeleton, ErrorBox, Empty, Button, useAsync } from "../components/ui";
import { getOrderSuggestions, confirmOrders } from "../lib/api";
import { won, man } from "../lib/format";

const tip = { borderRadius: 12, border: "1px solid #e2e8f0", fontSize: 12, boxShadow: "0 4px 12px rgba(0,0,0,.06)" };

function ErrorBadge({ rate }) {
  const high = rate >= 0.25;
  const mid = rate >= 0.15;
  const cls = high ? "bg-brand-50 text-brand-600" : mid ? "bg-cjorange-50 text-cjorange-700" : "bg-emerald-50 text-emerald-700";
  const label = high ? "오차 큼" : mid ? "보통" : "안정";
  return <span className={`rounded-md px-2 py-0.5 text-[11px] font-semibold ${cls}`}>{label} {Math.round(rate * 100)}%</span>;
}

export default function Ordering({ storeId, onToast }) {
  const { data, loading, error, reload } = useAsync(() => getOrderSuggestions(storeId), [storeId]);
  const [qty, setQty] = useState({});
  const [sending, setSending] = useState(false);
  const [done, setDone] = useState(false);
  const [pick, setPick] = useState(null);

  const items = data ?? [];
  const qtyOf = (i) => qty[i.product_id] ?? i.recommended_order;

  const totals = useMemo(() => {
    const before = items.reduce((s, i) => s + i.waste_risk_before, 0);
    const after = items.reduce((s, i) => s + i.waste_risk_after, 0);
    const cost = items.reduce((s, i) => s + qtyOf(i) * i.cost, 0);
    const avgErr = items.length ? items.reduce((s, i) => s + i.last_error_rate, 0) / items.length : 0;
    return { before, after, cost, avgErr };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items, qty]);

  const selected = pick ?? items[0];
  const forecastData = selected
    ? ["월", "화", "수", "목", "금", "토", "일"].map((day, idx) => ({
        day,
        예측수요: Math.round(selected.avg_daily_demand * (0.85 + (idx % 4) * 0.12)),
        발주기준: Math.round((qtyOf(selected) / 7) * 7 * 0.14 + selected.avg_daily_demand * 0.1),
      }))
    : [];

  const submit = async () => {
    setSending(true);
    try {
      const payload = items.map((i) => ({
        product_id: i.product_id,
        order_quantity: qtyOf(i),
        recommended_quantity: i.recommended_order,
      }));
      const res = await confirmOrders(storeId, payload);
      onToast({ title: `${res.ordered}건 발주 확정`, desc: `내일 입고 예정 · 예상 폐기위험 ${Math.round((1 - totals.after / totals.before) * 100)}% 감소` });
      setDone(true);
    } catch (e) {
      onToast({ tone: "error", title: "발주 실패", desc: e.message });
    }
    setSending(false);
  };

  if (error) return <ErrorBox message={error} onRetry={reload} />;

  return (
    <div className="space-y-6">
      <div className="flex items-start gap-2.5 rounded-2xl border border-cjblue-100 bg-cjblue-50 px-5 py-3.5">
        <Info size={15} className="mt-0.5 shrink-0 text-cjblue-600" />
        <p className="text-xs leading-relaxed text-cjblue-700">
          폐기는 <b>발주 시점</b>에 이미 결정됩니다. AI가 최근 판매 이력·요일·날씨를 반영해 예측한 수요를 기준으로
          적정 발주량을 제안합니다. 현재 담당자 발주 오차율 평균 <b>{Math.round(totals.avgErr * 100)}%</b>를 줄이는 것이 목표입니다.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi loading={loading} index={0} label="발주 제안" value={items.length} unit="품목" icon={PackagePlus} sub="내일 입고 기준" />
        <Kpi loading={loading} index={1} label="예상 발주 금액" value={man(totals.cost)} unit="만원" icon={TrendingUp} sub="원가 기준" />
        <Kpi loading={loading} index={2} tone="danger" label="현 발주 유지 시 폐기위험" value={man(totals.before)} unit="만원" sub="최근 오차율 반영" />
        <Kpi loading={loading} index={3} tone="ok" label="AI 제안 적용 시" value={man(totals.after)} unit="만원"
             icon={ShieldCheck} sub={totals.before ? `폐기위험 ${Math.round((1 - totals.after / totals.before) * 100)}% 감소` : ""} />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <Panel padded={false} title={<span>발주 제안 목록</span>}>
            {loading ? (
              <div className="space-y-3 p-5">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-12 w-full" />)}</div>
            ) : done ? (
              <Empty icon={ShieldCheck} title="발주 확정 완료" desc="내일 입고 후 재고에 반영됩니다." />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[620px] text-sm">
                  <thead>
                    <tr className="border-b border-slate-100 text-left text-xs text-slate-400">
                      <th className="px-5 py-3 font-medium">상품</th>
                      <th className="px-3 py-3 text-right font-medium">현재고</th>
                      <th className="px-3 py-3 text-right font-medium">7일 예측수요</th>
                      <th className="px-3 py-3 font-medium">발주 오차</th>
                      <th className="px-5 py-3 text-right font-medium">발주량</th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((i) => (
                      <tr key={i.product_id}
                          onClick={() => setPick(i)}
                          className={`cursor-pointer border-b border-slate-50 transition-colors last:border-0 hover:bg-slate-50 ${
                            selected?.product_id === i.product_id ? "bg-cjblue-50/50" : ""
                          }`}>
                        <td className="px-5 py-3">
                          <p className="font-semibold">{i.product_name}</p>
                          <p className="mt-0.5 text-xs text-slate-400">{i.category} · 원가 {won(i.cost)}원</p>
                        </td>
                        <td className="px-3 py-3 text-right text-slate-600">{i.stock_quantity}개</td>
                        <td className="px-3 py-3 text-right">
                          <span className="font-semibold">{i.forecast_7d}개</span>
                          <span className="ml-1 text-xs text-slate-400">일 {i.avg_daily_demand}</span>
                        </td>
                        <td className="px-3 py-3"><ErrorBadge rate={i.last_error_rate} /></td>
                        <td className="px-5 py-3">
                          <div className="flex items-center justify-end gap-2">
                            <span className="text-base font-bold">{qtyOf(i)}<span className="ml-0.5 text-xs font-medium text-slate-400">개</span></span>
                            <span className="inline-flex overflow-hidden rounded-lg border border-slate-200" onClick={(e) => e.stopPropagation()}>
                              <button onClick={() => setQty({ ...qty, [i.product_id]: Math.max(0, qtyOf(i) - 1) })}
                                      className="px-2 py-1 text-slate-500 hover:bg-slate-100"><Minus size={12} /></button>
                              <button onClick={() => setQty({ ...qty, [i.product_id]: qtyOf(i) + 1 })}
                                      className="border-l border-slate-200 px-2 py-1 text-slate-500 hover:bg-slate-100"><Plus size={12} /></button>
                            </span>
                          </div>
                          {qtyOf(i) !== i.recommended_order && (
                            <p className="mt-1 text-right text-[11px] text-cjorange-600">추천 {i.recommended_order}개에서 조정</p>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>
        </div>

        <Panel title={selected ? `${selected.product_name} 수요 예측` : "수요 예측"}
               right={<span className="rounded-md bg-cjblue-50 px-2 py-0.5 text-[11px] font-semibold text-cjblue-700">AI 예측</span>}>
          <div className="h-48">
            {loading || !selected ? <Skeleton className="h-full w-full" /> : (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={forecastData} margin={{ top: 6, right: 6, left: -22, bottom: 0 }}>
                  <defs>
                    <linearGradient id="gDemand" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#0072BC" stopOpacity={0.25} />
                      <stop offset="100%" stopColor="#0072BC" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
                  <XAxis dataKey="day" tickLine={false} axisLine={false} tick={{ fontSize: 11, fill: "#94a3b8" }} />
                  <YAxis tickLine={false} axisLine={false} tick={{ fontSize: 11, fill: "#94a3b8" }} />
                  <Tooltip contentStyle={tip} formatter={(v) => [`${v}개`, "예측 수요"]} />
                  <Area type="monotone" dataKey="예측수요" stroke="#0072BC" strokeWidth={2.2} fill="url(#gDemand)" />
                </AreaChart>
              </ResponsiveContainer>
            )}
          </div>
          {selected && !loading && (
            <div className="mt-3 space-y-1.5 text-xs">
              <div className="flex justify-between"><span className="text-slate-500">현재고</span><b>{selected.stock_quantity}개</b></div>
              <div className="flex justify-between"><span className="text-slate-500">7일 예측수요</span><b>{selected.forecast_7d}개</b></div>
              <div className="flex justify-between"><span className="text-slate-500">AI 권장 발주</span><b className="text-cjblue-700">{selected.recommended_order}개</b></div>
              <div className="flex justify-between border-t border-slate-100 pt-1.5">
                <span className="text-slate-500">폐기위험 변화</span>
                <b className="text-emerald-600">{man(selected.waste_risk_before)} → {man(selected.waste_risk_after)}만원</b>
              </div>
            </div>
          )}
        </Panel>
      </div>

      {!done && !loading && items.length > 0 && (
        <div className="sticky bottom-4 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-slate-200 bg-white/95 px-5 py-4 shadow-lg backdrop-blur">
          <p className="text-sm text-slate-600">
            {items.length}품목 · 발주 금액 <b className="text-slate-900">{man(totals.cost)}만원</b> · 폐기위험{" "}
            <b className="text-emerald-600">{Math.round((1 - totals.after / totals.before) * 100)}% 감소 예상</b>
          </p>
          <div className="flex gap-2">
            <Button onClick={() => setQty({})}>추천값으로 초기화</Button>
            <Button variant="primary" onClick={submit} disabled={sending}>
              {sending ? <Loader2 size={15} className="animate-spin" /> : <Check size={15} />}
              {sending ? "발주 중" : "발주 확정"}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
