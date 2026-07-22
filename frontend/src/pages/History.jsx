import { useState, useMemo } from "react";
import { Check, AlertTriangle, MinusCircle, Search, Download, Sparkles } from "lucide-react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Cell, ReferenceLine } from "recharts";
import { Panel, Skeleton, ErrorBox, Empty, Button, useAsync } from "../components/ui";
import { getHistory } from "../lib/api";
import { won, man } from "../lib/format";

const tip = { borderRadius: 12, border: "1px solid #cbd5e1", fontSize: 12, boxShadow: "0 4px 14px rgba(0,0,0,.10)", background: "#ffffff", color: "#0f172a" };

const RESULT = {
  sold: { label: "완판", cls: "bg-emerald-50 text-emerald-700", icon: Check },
  partial: { label: "일부 판매", cls: "bg-cjorange-50 text-cjorange-700", icon: MinusCircle },
  wasted: { label: "폐기 발생", cls: "bg-brand-50 text-brand-600", icon: AlertTriangle },
};

export default function History({ storeId, onToast }) {
  const { data, loading, error, reload } = useAsync(() => getHistory(storeId), [storeId]);
  const [q, setQ] = useState("");
  const rows = data ?? [];

  const filtered = useMemo(
    () => (q.trim() ? rows.filter((r) => r.product_name.includes(q.trim()) || r.user.includes(q.trim())) : rows),
    [rows, q]
  );

  /* 카테고리별 조정 패턴 — AI 추천 대비 담당자가 얼마나 낮추/올리는가 */
  const pattern = useMemo(() => {
    const m = {};
    rows.forEach((r) => {
      const gap = Math.round((r.approved_rate - r.recommended_rate) * 100);
      (m[r.category] ??= []).push(gap);
    });
    return Object.entries(m)
      .map(([name, arr]) => ({ name, gap: +(arr.reduce((a, b) => a + b, 0) / arr.length).toFixed(1), n: arr.length }))
      .sort((a, b) => a.gap - b.gap);
  }, [rows]);

  const exportCsv = () => {
    const head = ["승인ID", "일시", "담당자", "상품명", "카테고리", "AI추천율", "승인율", "조정폭(%p)", "결과", "판매수량", "재고수량", "매출액"];
    const body = filtered.map((r) => [
      r.id, r.date, r.user, r.product_name, r.category,
      `${Math.round(r.recommended_rate * 100)}%`,
      `${Math.round(r.approved_rate * 100)}%`,
      Math.round((r.approved_rate - r.recommended_rate) * 100),
      { sold: "완판", partial: "일부 판매", wasted: "폐기 발생" }[r.result] ?? r.result,
      r.sold_qty, r.stock_quantity, r.revenue,
    ]);
    const esc = (v) => {
      const t = String(v == null ? "" : v);
      const needsQuote = t.indexOf(",") >= 0 || t.indexOf("\n") >= 0 || t.indexOf(String.fromCharCode(34)) >= 0;
      if (!needsQuote) return t;
      const q = String.fromCharCode(34);
      return q + t.split(q).join(q + q) + q;
    };
    const csv = [head, ...body].map((row) => row.map(esc).join(",")).join("\r\n");
    const blob = new Blob(["\uFEFF" + csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    const today = new Date().toISOString().slice(0, 10).replace(/-/g, "");
    a.href = url;
    a.download = `승인이력_${storeId}_${today}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    onToast({ title: "CSV 다운로드 완료", desc: `승인 이력 ${filtered.length}건 · 엑셀에서 열 수 있습니다` });
  };

  const adjusted = rows.filter((r) => r.approved_rate !== r.recommended_rate).length;
  const wastedAfterAdjust = rows.filter((r) => r.approved_rate < r.recommended_rate && r.result === "wasted").length;

  if (error) return <ErrorBox message={error} onRetry={reload} />;

  return (
    <div className="space-y-5">
      <div className="grid gap-4 lg:grid-cols-3">
        <Panel className="lg:col-span-2" title="카테고리별 조정 패턴"
               right={<span className="rounded-md bg-cjblue-50 px-2 py-0.5 text-[11px] font-semibold text-cjblue-700">학습 데이터</span>}>
          <p className="mb-3 text-xs leading-relaxed text-slate-500">
            담당자가 AI 추천보다 얼마나 낮추거나 올렸는지의 평균입니다. 이 패턴을 모델에 반영하면 추천이 현장에 더 맞게 조정됩니다.
          </p>
          <div className="h-44">
            {loading ? <Skeleton className="h-full w-full" /> : (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={pattern} margin={{ top: 6, right: 10, left: -20, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" strokeOpacity={0.5} vertical={false} />
                  <XAxis dataKey="name" tickLine={false} axisLine={false} tick={{ fontSize: 12, fill: "#8b95a5" }} />
                  <YAxis tickLine={false} axisLine={false} tick={{ fontSize: 11, fill: "#8b95a5" }} tickFormatter={(v) => `${v}%p`} />
                  <Tooltip contentStyle={tip} formatter={(v, _n, p) => [`${v}%p (${p.payload.n}건)`, "평균 조정폭"]} />
                  <ReferenceLine y={0} stroke="#cbd5e1" />
                  <Bar dataKey="gap" radius={[6, 6, 6, 6]} barSize={30}>
                    {pattern.map((p, i) => <Cell key={i} fill={p.gap < 0 ? "#E4002B" : "#059669"} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>
        </Panel>

        <Panel title="조정의 결과">
          {loading ? <Skeleton className="h-40 w-full" /> : (
            <div className="space-y-3">
              <div className="rounded-xl bg-slate-50 px-4 py-3">
                <p className="text-xs text-slate-500">추천값 조정 건수</p>
                <p className="mt-1 text-2xl font-bold">{adjusted}<span className="ml-1 text-xs font-semibold text-slate-400">/ {rows.length}건</span></p>
              </div>
              <div className="rounded-xl bg-brand-50 px-4 py-3">
                <p className="text-xs text-brand-600">추천보다 낮춰서 폐기 발생</p>
                <p className="mt-1 text-2xl font-bold text-brand-600">{wastedAfterAdjust}건</p>
                <p className="mt-1 text-[11px] leading-relaxed text-brand-500">
                  할인을 덜 한 건들에서 폐기가 반복되면 추천을 신뢰해도 된다는 근거가 됩니다.
                </p>
              </div>
              <div className="flex items-start gap-2 rounded-xl bg-cjblue-50 px-4 py-3">
                <Sparkles size={13} className="mt-0.5 shrink-0 text-cjblue-600" />
                <p className="text-[11px] leading-relaxed text-cjblue-800">
                  축산에서 평균 <b>{pattern.find((p) => p.name === "축산")?.gap ?? 0}%p</b> 낮추는 경향이 확인됩니다.
                  다음 학습에 반영 예정입니다.
                </p>
              </div>
            </div>
          )}
        </Panel>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <div className="relative min-w-56 flex-1">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="상품명 또는 담당자 검색"
                 className="w-full rounded-xl border border-slate-200 py-2.5 pl-9 pr-3 text-sm outline-none transition-colors focus:border-brand-500 focus:ring-4 focus:ring-brand-50" />
        </div>
        <Button onClick={exportCsv} disabled={filtered.length === 0}>
          <Download size={14} /> CSV 내보내기
        </Button>
      </div>

      <Panel padded={false}>
        {loading ? (
          <div className="space-y-3 p-5">{[0, 1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-11 w-full" />)}</div>
        ) : filtered.length === 0 ? (
          <Empty icon={Search} title="검색 결과가 없습니다" desc="다른 검색어를 입력해보세요." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-sm">
              <thead>
                <tr className="border-b border-slate-100 text-left text-xs text-slate-400">
                  <th className="px-5 py-3 font-medium">일시 · 담당자</th>
                  <th className="px-3 py-3 font-medium">상품</th>
                  <th className="px-3 py-3 text-center font-medium">AI 추천</th>
                  <th className="px-3 py-3 text-center font-medium">승인</th>
                  <th className="px-3 py-3 text-center font-medium">결과</th>
                  <th className="px-5 py-3 text-right font-medium">매출</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((r) => {
                  const gap = Math.round((r.approved_rate - r.recommended_rate) * 100);
                  const R = RESULT[r.result];
                  return (
                    <tr key={r.id} className="border-b border-slate-50 transition-colors last:border-0 hover:bg-slate-50">
                      <td className="px-5 py-3">
                        <p className="text-xs text-slate-500">{r.date}</p>
                        <p className="text-xs font-semibold text-slate-700">{r.user}</p>
                      </td>
                      <td className="px-3 py-3">
                        <p className="font-semibold">{r.product_name}</p>
                        <p className="text-xs text-slate-400">{r.category} · {r.sold_qty}/{r.stock_quantity}개 판매</p>
                      </td>
                      <td className="px-3 py-3 text-center text-slate-500">{Math.round(r.recommended_rate * 100)}%</td>
                      <td className="px-3 py-3 text-center">
                        <span className="font-bold">{Math.round(r.approved_rate * 100)}%</span>
                        {gap !== 0 && (
                          <span className={`ml-1 text-[11px] font-semibold ${gap < 0 ? "text-brand-600" : "text-emerald-600"}`}>
                            {gap > 0 ? "+" : ""}{gap}%p
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-3 text-center">
                        <span className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[11px] font-semibold ${R.cls}`}>
                          <R.icon size={11} /> {R.label}
                        </span>
                      </td>
                      <td className="px-5 py-3 text-right font-semibold">{won(r.revenue)}원</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <p className="text-xs text-slate-400">
        가격 변경은 전건 기록되며 담당자·시각·추천값·승인값이 함께 저장됩니다. (감사 추적 · 모델 재학습 데이터)
      </p>
    </div>
  );
}
