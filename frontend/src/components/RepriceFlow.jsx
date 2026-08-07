import { useState } from "react";
import {
  Sparkles, Loader2, Check, X, ArrowRight, ShieldCheck, Ban, Minus, Plus,
  Undo2, UserCheck, TrendingDown,
} from "lucide-react";
import { REJECT_REASONS, MAX_REPRICE_ROUNDS } from "../lib/api";
import { won, man, discounted } from "../lib/format";

const labelOf = (code) => REJECT_REASONS.find((r) => r.code === code)?.label ?? "기타";

/* 반려 이후 업무 흐름을 한 줄로 보여주는 단계 표시 */
function Stepper({ stage }) {
  const steps = [
    { key: "rejected", label: "점장 반려" },
    { key: "calc", label: "AI 재계산" },
    { key: "review", label: "담당자 재검토" },
    { key: "done", label: "확정 · ESL 반영" },
  ];
  const idx = steps.findIndex((s) => s.key === stage);
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {steps.map((s, i) => (
        <span key={s.key} className="flex items-center gap-1.5">
          <span className={`rounded-md px-2 py-0.5 text-[10px] font-bold transition-colors ${
            i < idx ? "bg-slate-100 text-slate-400"
            : i === idx ? "bg-slate-900 text-white"
            : "bg-slate-50 text-slate-300"
          }`}>
            {s.label}
          </span>
          {i < steps.length - 1 && <ArrowRight size={10} className="text-slate-300" />}
        </span>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------
   반려 → 재추천 → 재검토 대기열
   ------------------------------------------------------------------
   점장이 반려한 건이 사라지지 않고 이 패널에서 계속 추적됩니다.
   calculating : AI가 제약을 반영해 재계산 중
   restaged    : 새 추천안 도착 · 담당자 재검토 대기
   closed      : 재추천 한도 소진 후 수동 지정 / 할인 미적용으로 종결
   ------------------------------------------------------------------ */
export default function RepriceFlow({
  repricing, restaged, closed, canApprove, threshold,
  onAccept, onReReject, onFinalizeManual, onDiscard,
}) {
  const [draft, setDraft] = useState({});   // 수동 지정 할인율 임시값

  const calcList = [...repricing.values()];
  const stageList = [...restaged.values()];
  const closedList = [...closed.values()];
  if (!calcList.length && !stageList.length && !closedList.length) return null;

  const total = calcList.length + stageList.length + closedList.length;

  return (
    <div className="overflow-hidden rounded-2xl border border-cjblue-100 bg-white">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-cjblue-100 bg-cjblue-50 px-5 py-3">
        <div className="flex flex-wrap items-center gap-2">
          <Undo2 size={15} className="text-cjblue-700" />
          <p className="text-sm font-bold text-cjblue-700">반려 후속 처리 {total}건</p>
          {calcList.length > 0 && (
            <span className="flex items-center gap-1 rounded-md bg-white px-2 py-0.5 text-[11px] font-semibold text-cjblue-700">
              <Loader2 size={10} className="animate-spin" /> 재계산 {calcList.length}
            </span>
          )}
          {stageList.length > 0 && (
            <span className="rounded-md bg-white px-2 py-0.5 text-[11px] font-semibold text-cjblue-700">
              재검토 대기 {stageList.length}
            </span>
          )}
          {closedList.length > 0 && (
            <span className="rounded-md bg-white px-2 py-0.5 text-[11px] font-semibold text-slate-500">
              종결 {closedList.length}
            </span>
          )}
        </div>
        <Stepper stage={calcList.length ? "calc" : stageList.length ? "review" : "done"} />
      </div>

      {/* ---- ① AI 재계산 중 ---- */}
      {calcList.map((i) => (
        <div key={i.product_id} className="border-b border-slate-100 px-5 py-4 last:border-0">
          <div className="flex flex-wrap items-center gap-3">
            <Loader2 size={15} className="shrink-0 animate-spin text-cjblue-600" />
            <span className="w-44 shrink-0 truncate text-sm font-semibold">{i.product_name}</span>
            <span className="rounded-md bg-slate-100 px-2 py-0.5 text-xs font-bold text-slate-400 line-through">
              −{i.rate}%
            </span>
            <span className="min-w-0 flex-1 text-xs text-slate-500">
              AI가 새로운 할인율을 계산 중입니다 · 반려 사유 <b className="text-slate-700">{labelOf(i.reason_code)}</b>
              {i.memo ? ` · "${i.memo}"` : ""}
            </span>
            <span className="shrink-0 text-[11px] font-semibold text-cjblue-600">{i.round}차 재추천</span>
          </div>
          <div className="mt-2.5 h-1 overflow-hidden rounded-full bg-slate-100">
            <div className="h-full w-1/3 animate-indeterminate rounded-full bg-cjblue-500" />
          </div>
          <p className="mt-1.5 text-[11px] text-slate-400">
            제약 반영 → 할인율별 손익곡선 재계산 → 순이익 최대점 재탐색
          </p>
        </div>
      ))}

      {/* ---- ② 재추천 결과 · 담당자 재검토 ---- */}
      {stageList.map((i) => {
        const rec = i.reprice;
        const price = discounted(i.regular_price, rec.new_rate / 100);
        const noAction = rec.new_rate === 0;
        return (
          <div key={i.product_id} className="border-b border-slate-100 px-5 py-4 last:border-0">
            <div className="flex flex-wrap items-start gap-3">
              <Sparkles size={15} className="mt-0.5 shrink-0 text-cjblue-600" />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-bold">{i.product_name}</span>
                  <span className="rounded-md bg-cjblue-50 px-2 py-0.5 text-[11px] font-bold text-cjblue-700">
                    {rec.round}차 재추천
                  </span>
                  <span className="rounded-md bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-500">
                    반려 사유 {labelOf(rec.reason_code)}
                  </span>
                  {rec.needs_manager ? (
                    <span className="flex items-center gap-1 rounded-md bg-brand-50 px-2 py-0.5 text-[11px] font-semibold text-brand-600">
                      <ShieldCheck size={10} /> 점장 재승인 필요
                    </span>
                  ) : !noAction && (
                    <span className="flex items-center gap-1 rounded-md bg-emerald-50 px-2 py-0.5 text-[11px] font-semibold text-emerald-700">
                      <UserCheck size={10} /> 담당자 승인만으로 확정
                    </span>
                  )}
                </div>
                <p className="mt-1.5 text-xs leading-relaxed text-slate-500">{rec.ai_note}</p>
                {rec.memo && <p className="mt-1 text-[11px] text-slate-400">점장 메모 · “{rec.memo}”</p>}
                {rec.gain_delta < 0 && (
                  <p className="mt-1 flex items-center gap-1 text-[11px] font-medium text-cjorange-700">
                    <TrendingDown size={11} />
                    반려로 포기한 순이익 {man(Math.abs(rec.gain_delta))}만원 · 재고 {i.stock_quantity}개 기준
                  </p>
                )}
              </div>

              <div className="shrink-0 text-right">
                <p className="text-xs text-slate-400">
                  <span className="line-through">−{rec.previous_rate}%</span>
                  <ArrowRight size={10} className="mx-1 inline text-slate-300" />
                  <b className="text-cjblue-700">−{rec.new_rate}%</b>
                </p>
                <p className="text-lg font-bold tracking-tight">
                  {noAction ? "정가 유지" : `${won(price)}원`}
                </p>
                <p className="mt-0.5 text-[11px] text-slate-400">
                  {noAction ? "할인 실익 없음" : `예상 소진율 ${rec.prob}% · 상한 ${rec.cap}%`}
                </p>
              </div>
            </div>

            <div className="mt-3 flex flex-wrap justify-end gap-2">
              {rec.round >= MAX_REPRICE_ROUNDS && (
                <span className="mr-auto self-center text-[11px] font-medium text-cjorange-700">
                  재추천 한도 도달 · 다음 반려는 수동 지정 또는 할인 미적용으로 종결됩니다
                </span>
              )}
              {canApprove && (
                <>
                  <button onClick={() => onDiscard(i.product_id)}
                          className="rounded-xl border border-slate-200 bg-white px-3.5 py-2 text-xs font-semibold text-slate-500 hover:bg-slate-50">
                    <Ban size={12} className="mr-1 inline" /> 할인 미적용
                  </button>
                  <button onClick={() => onReReject(i)}
                          className="rounded-xl border border-slate-200 bg-white px-3.5 py-2 text-xs font-semibold text-slate-600 hover:bg-slate-50">
                    <X size={12} className="mr-1 inline" /> 다시 반려
                  </button>
                </>
              )}
              <button onClick={() => onAccept(i.product_id)} disabled={noAction || (rec.needs_manager && !canApprove)}
                      title={rec.needs_manager && !canApprove ? "점장 계정으로 로그인해야 승인할 수 있습니다" : ""}
                      className="rounded-xl bg-brand-600 px-4 py-2 text-xs font-bold text-white transition-transform active:scale-95 disabled:pointer-events-none disabled:opacity-40">
                <Check size={12} strokeWidth={3} className="mr-1 inline" />
                {rec.needs_manager ? `${threshold}% 초과 · 점장 결재 요청` : "재검토 승인 · ESL 반영"}
              </button>
            </div>
          </div>
        );
      })}

      {/* ---- ③ 강제 종결 ---- */}
      {closedList.map((i) => {
        const manual = i.mode === "manual";
        const rate = draft[i.product_id] ?? i.rate ?? 0;
        return (
          <div key={i.product_id} className="flex flex-wrap items-center gap-3 border-b border-slate-100 bg-slate-50/60 px-5 py-3.5 last:border-0">
            {manual ? <UserCheck size={14} className="shrink-0 text-slate-500" /> : <Ban size={14} className="shrink-0 text-slate-400" />}
            <span className="w-44 shrink-0 truncate text-sm font-semibold">{i.product_name}</span>
            {manual ? (
              <>
                <span className="rounded-md bg-slate-200 px-2 py-0.5 text-[11px] font-bold text-slate-600">수동 지정</span>
                <span className="min-w-0 flex-1 text-xs text-slate-500">
                  재추천 {MAX_REPRICE_ROUNDS}회 소진 · 점장이 직접 할인율을 확정합니다
                </span>
                <span className="flex shrink-0 items-center gap-1.5">
                  <button onClick={() => setDraft({ ...draft, [i.product_id]: Math.max(0, rate - 1) })}
                          className="rounded-lg border border-slate-200 bg-white px-1.5 py-1 text-slate-500 hover:bg-slate-100">
                    <Minus size={12} />
                  </button>
                  <span className="w-12 text-center text-sm font-bold">−{rate}%</span>
                  <button onClick={() => setDraft({ ...draft, [i.product_id]: Math.min(i.cap ?? 40, rate + 1) })}
                          className="rounded-lg border border-slate-200 bg-white px-1.5 py-1 text-slate-500 hover:bg-slate-100">
                    <Plus size={12} />
                  </button>
                  <button onClick={() => onFinalizeManual(i.product_id, rate)} disabled={!canApprove}
                          className="ml-1 rounded-lg bg-slate-900 px-3 py-1.5 text-xs font-bold text-white active:scale-95 disabled:opacity-40">
                    확정
                  </button>
                </span>
              </>
            ) : (
              <>
                <span className="rounded-md bg-slate-200 px-2 py-0.5 text-[11px] font-bold text-slate-600">할인 미적용</span>
                <span className="min-w-0 flex-1 text-xs text-slate-500">
                  정가 유지 · 미판매분 폐기 처리 · 손실 {man(i.expected_loss)}만원 반영
                </span>
              </>
            )}
          </div>
        );
      })}

      <p className="border-t border-slate-100 bg-white px-5 py-2.5 text-[11px] leading-relaxed text-slate-400">
        반려는 프로세스 종료가 아니라 제약 추가입니다. 반려 사유가 AI의 할인 상한 제약으로 전달되고,
        재추천은 최대 {MAX_REPRICE_ROUNDS}회까지만 반복한 뒤 수동 지정 또는 할인 미적용으로 반드시 종결됩니다.
      </p>
    </div>
  );
}
