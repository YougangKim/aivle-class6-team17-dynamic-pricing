import { useState } from "react";
import { X, Undo2, AlertTriangle, Sparkles, Ban } from "lucide-react";
import { REJECT_REASONS, MAX_REPRICE_ROUNDS } from "../lib/api";
import { Button } from "./ui";
import { man } from "../lib/format";

/* ------------------------------------------------------------------
   점장 반려 모달
   ------------------------------------------------------------------
   반려는 사유 없이 받지 않습니다. 사유가 곧 AI 재추천의 제약조건이 되고,
   승인 이력에 "왜 반려했는지"가 남아야 정책 튜닝(상한 조정)에 쓸 수 있습니다.
   재추천 한도(MAX_REPRICE_ROUNDS)를 넘긴 건은 재추천 대신 강제 종결 분기로
   안내합니다.
   ------------------------------------------------------------------ */
export default function RejectModal({ targets, round = 0, onClose, onSubmit, onForceClose }) {
  const [code, setCode] = useState("rate_too_high");
  const [memo, setMemo] = useState("");
  const exhausted = round >= MAX_REPRICE_ROUNDS;
  const reason = REJECT_REASONS.find((r) => r.code === code);
  const list = targets ?? [];
  const loss = list.reduce((s, i) => s + (i.expected_loss ?? 0), 0);

  return (
    <div className="fixed inset-0 z-[55] flex items-end justify-center bg-slate-900/50 p-0 backdrop-blur-sm sm:items-center sm:p-6"
         onClick={onClose}>
      <div className="animate-fade-up max-h-[92vh] w-full max-w-lg overflow-y-auto rounded-t-3xl bg-white shadow-2xl sm:rounded-3xl"
           onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between border-b border-slate-100 px-6 py-5">
          <div>
            <h2 className="flex items-center gap-2 text-lg font-bold tracking-tight">
              <Undo2 size={18} className="text-brand-600" />
              {exhausted ? "재추천 한도 도달" : "반려 사유 선택"}
            </h2>
            <p className="mt-1 text-xs text-slate-500">
              {list.length}건 · 미판매 시 손실 {man(loss)}만원
              {round > 0 && <span className="ml-1.5 text-brand-600">· 재추천 {round}회 진행됨</span>}
            </p>
          </div>
          <button onClick={onClose} className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100">
            <X size={18} />
          </button>
        </div>

        {exhausted ? (
          /* ---- 재추천 2회 소진 → 강제 종결 분기 ---- */
          <div className="px-6 py-5">
            <div className="flex gap-2.5 rounded-2xl bg-cjorange-50 px-4 py-3">
              <AlertTriangle size={15} className="mt-0.5 shrink-0 text-cjorange-600" />
              <p className="text-xs leading-relaxed text-cjorange-700">
                이 상품은 AI 재추천을 {MAX_REPRICE_ROUNDS}회 거쳤습니다. 반복 재추천은 마감 시각까지 남은
                판매 시간을 소모하므로 여기서 종결합니다. 아래 두 가지 중 하나를 선택하세요.
              </p>
            </div>
            <div className="mt-4 space-y-2">
              <button onClick={() => onForceClose("manual")}
                      className="flex w-full items-start gap-3 rounded-2xl border border-slate-200 px-4 py-3.5 text-left transition-colors hover:border-brand-200 hover:bg-brand-50/40">
                <Sparkles size={16} className="mt-0.5 shrink-0 text-brand-600" />
                <span>
                  <span className="block text-sm font-bold">점장 수동 가격 지정</span>
                  <span className="mt-0.5 block text-xs text-slate-500">
                    AI 추천을 쓰지 않고 점장이 직접 할인율을 입력해 즉시 확정합니다. 이력에 <b>수동 지정</b>으로 기록됩니다.
                  </span>
                </span>
              </button>
              <button onClick={() => onForceClose("no_discount")}
                      className="flex w-full items-start gap-3 rounded-2xl border border-slate-200 px-4 py-3.5 text-left transition-colors hover:border-slate-300 hover:bg-slate-50">
                <Ban size={16} className="mt-0.5 shrink-0 text-slate-500" />
                <span>
                  <span className="block text-sm font-bold">할인 미적용 · 폐기 처리</span>
                  <span className="mt-0.5 block text-xs text-slate-500">
                    정가를 유지하고 미판매분은 폐기로 마감합니다. 손실 {man(loss)}만원이 그대로 반영됩니다.
                  </span>
                </span>
              </button>
            </div>
          </div>
        ) : (
          <>
            <div className="px-6 py-5">
              <p className="text-xs font-semibold text-slate-500">
                반려 사유는 AI 재추천의 제약조건으로 전달됩니다
              </p>
              <div className="mt-2.5 space-y-1.5">
                {REJECT_REASONS.map((r) => (
                  <button key={r.code} onClick={() => setCode(r.code)}
                          className={`flex w-full items-center gap-3 rounded-xl border px-4 py-3 text-left transition-all ${
                            code === r.code
                              ? "border-brand-600 bg-brand-50/60 ring-1 ring-brand-600"
                              : "border-slate-200 hover:border-slate-300 hover:bg-slate-50"
                          }`}>
                    <span className={`h-3.5 w-3.5 shrink-0 rounded-full border-[4px] transition-all ${
                      code === r.code ? "border-brand-600" : "border-slate-200"
                    }`} />
                    <span className="min-w-0 flex-1">
                      <span className="block text-sm font-semibold">{r.label}</span>
                      <span className="block text-[11px] text-slate-500">{r.desc}</span>
                    </span>
                    <span className="shrink-0 rounded-md bg-slate-100 px-2 py-0.5 text-[11px] font-bold text-slate-600">
                      상한 −{r.cut}%p
                    </span>
                  </button>
                ))}
              </div>

              <label className="mt-4 block text-xs font-semibold text-slate-500">
                메모 <span className="font-normal text-slate-400">(선택 · 승인 이력에 남습니다)</span>
              </label>
              <textarea value={memo} onChange={(e) => setMemo(e.target.value)} rows={2}
                        placeholder="예) 주말 전단행사 품목과 중복되어 다음 주 재검토"
                        className="mt-1.5 w-full resize-none rounded-xl border border-slate-200 px-3.5 py-2.5 text-sm outline-none transition-colors placeholder:text-slate-300 focus:border-brand-500" />

              <div className="mt-4 flex gap-2.5 rounded-2xl bg-cjblue-50 px-4 py-3">
                <Sparkles size={15} className="mt-0.5 shrink-0 text-cjblue-600" />
                <p className="text-xs leading-relaxed text-cjblue-700">
                  반려하면 프로세스가 종료되지 않습니다. <b>{reason?.label}</b> 제약을 반영해 할인 상한을{" "}
                  <b>{reason?.cut}%p</b> 낮춘 뒤 AI가 순이익 최대점을 다시 계산하고, 새 추천안이 담당자 재검토
                  대기열로 돌아갑니다. (재추천 최대 {MAX_REPRICE_ROUNDS}회)
                </p>
              </div>
            </div>

            <div className="flex justify-end gap-2 border-t border-slate-100 px-6 py-4">
              <Button onClick={onClose}>취소</Button>
              <Button variant="primary" onClick={() => onSubmit({ code, memo })}>
                <Undo2 size={15} /> 반려 · AI 재추천 요청
              </Button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
