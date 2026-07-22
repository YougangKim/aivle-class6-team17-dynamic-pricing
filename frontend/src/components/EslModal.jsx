import { X, Send, CheckCircle2, AlertTriangle, RefreshCw, Printer } from "lucide-react";
import { Skeleton, Button, useAsync } from "./ui";
import { getEslStatus } from "../lib/api";

const STATUS = {
  ok: { dot: "bg-emerald-500", label: "반영 완료", cls: "text-emerald-600" },
  failed: { dot: "bg-brand-500", label: "전송 실패", cls: "text-brand-600" },
  manual: { dot: "bg-violet-500", label: "수기 필요", cls: "text-violet-600" },
};

export default function EslModal({ storeId, approved, onClose, onToast }) {
  const { data, loading, reload } = useAsync(() => getEslStatus(storeId), [storeId]);

  const extra = [...(approved?.values() ?? [])].map((a, i) => ({
    product_name: a.name,
    label_id: a.esl ? `A-${1100 + i}` : "-",
    status: a.esl ? "ok" : "manual",
    detail: a.esl ? `방금 반영 완료 · ${a.rate}% 할인` : "ESL 미적용 품목 · 수기 라벨 필요",
    elapsed: "방금",
    action: a.esl ? undefined : "print",
  }));
  const logs = [...extra, ...(data?.logs ?? [])];
  const sent = (data?.sent_today ?? 0) + extra.length;
  const applied = (data?.applied ?? 0) + extra.filter((e) => e.status === "ok").length;
  const failed = (data?.failed ?? 0) + extra.filter((e) => e.status !== "ok").length;

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-slate-900/50 backdrop-blur-sm sm:items-center sm:p-6" onClick={onClose}>
      <div className="animate-fade-up max-h-[88vh] w-full max-w-2xl overflow-y-auto rounded-t-3xl bg-white shadow-2xl sm:rounded-3xl" onClick={(e) => e.stopPropagation()}>
        <div className="sticky top-0 flex items-start justify-between border-b border-slate-100 bg-white/95 px-6 py-5 backdrop-blur">
          <div>
            <h2 className="text-lg font-bold tracking-tight">ESL 전송 현황</h2>
            <p className="mt-0.5 text-xs text-slate-500">승인한 가격이 전자라벨에 반영된 결과입니다.</p>
          </div>
          <button onClick={onClose} className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-slate-100"><X size={18} /></button>
        </div>

        <div className="space-y-5 px-6 py-5">
          <div className="grid gap-3 sm:grid-cols-3">
            {loading ? [0, 1, 2].map((i) => <Skeleton key={i} className="h-20 w-full" />) : [
              { l: "오늘 전송", v: sent, i: Send, c: "bg-slate-50 text-slate-900" },
              { l: "반영 완료", v: applied, i: CheckCircle2, c: "bg-emerald-50 text-emerald-700" },
              { l: "조치 필요", v: failed, i: AlertTriangle, c: "bg-brand-50 text-brand-600" },
            ].map(({ l, v, i: Icon, c }) => (
              <div key={l} className={`rounded-2xl px-4 py-3.5 ${c}`}>
                <div className="flex items-center justify-between">
                  <p className="text-xs font-medium opacity-80">{l}</p>
                  <Icon size={15} className="opacity-50" />
                </div>
                <p className="mt-1 text-2xl font-bold">{v}<span className="ml-0.5 text-xs font-semibold">건</span></p>
              </div>
            ))}
          </div>

          <div className="overflow-hidden rounded-2xl border border-slate-200">
            {loading ? (
              <div className="space-y-3 p-4">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-8 w-full" />)}</div>
            ) : (
              logs.map((l, i) => {
                const st = STATUS[l.status];
                return (
                  <div key={i} className="flex flex-wrap items-center gap-3 border-b border-slate-100 px-4 py-3 last:border-0">
                    <span className={`h-2 w-2 shrink-0 rounded-full ${st.dot}`} />
                    <span className="w-40 shrink-0 truncate text-sm font-semibold">{l.product_name}</span>
                    <span className={`w-20 shrink-0 text-xs font-medium ${st.cls}`}>{st.label}</span>
                    <span className="min-w-0 flex-1 truncate text-xs text-slate-500">
                      {l.label_id !== "-" && <span className="mr-2 font-mono text-slate-400">{l.label_id}</span>}
                      {l.detail}
                    </span>
                    {l.status === "ok" ? (
                      <span className="text-xs text-slate-400">{l.elapsed}</span>
                    ) : (
                      <Button variant="small" onClick={() => onToast({ title: l.action === "retry" ? "재전송 요청됨" : "라벨 인쇄 요청됨", desc: l.product_name })}>
                        {l.action === "retry" ? <RefreshCw size={12} /> : <Printer size={12} />}
                        {l.action === "retry" ? "재전송" : "인쇄"}
                      </Button>
                    )}
                  </div>
                );
              })
            )}
          </div>

          <p className="rounded-xl bg-slate-50 px-4 py-3 text-xs leading-relaxed text-slate-500">
            무게 측정 상품(정육·수산 일부)은 ESL이 부착되지 않아 자동 반영 대상에서 제외됩니다.
            해당 품목은 <b className="text-violet-600">수기 라벨</b>로 분류되며, 인쇄 버튼으로 가격표를 출력해 부착해주세요.
          </p>
        </div>

        <div className="sticky bottom-0 flex justify-end gap-2 border-t border-slate-100 bg-white/95 px-6 py-4 backdrop-blur">
          <Button onClick={reload}><RefreshCw size={13} /> 새로고침</Button>
          <Button variant="primary" onClick={onClose}>닫기</Button>
        </div>
      </div>
    </div>
  );
}
