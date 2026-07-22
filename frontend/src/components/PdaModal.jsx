import { useState } from "react";
import { X, ScanLine, Check, ChevronLeft, Wifi, WifiOff, Battery, Signal, CloudUpload, Loader2 } from "lucide-react";
import { won, man, discounted } from "../lib/format";
import { APPROVAL_THRESHOLD } from "../lib/api";
import { BrandMark } from "./ui";

/* 현장 PDA 모드 — 매대에서 상품을 스캔해 즉시 승인하는 화면 */
export default function PdaModal({ items, approvedIds, onApprove, onClose, onToast }) {
  const [scanning, setScanning] = useState(false);
  const [picked, setPicked] = useState(null);
  const [rate, setRate] = useState(0);
  const [offline, setOffline] = useState(false);
  const [queue, setQueue] = useState([]);
  const [syncing, setSyncing] = useState(false);

  const queuedIds = new Set(queue.map((q) => q.product_id));
  const pending = items.filter((i) => !approvedIds.has(i.product_id) && !queuedIds.has(i.product_id));

  const scan = (item) => {
    setScanning(true);
    setTimeout(() => {
      setScanning(false);
      setPicked(item);
      setRate(Math.round(item.recommended_rate * 100));
    }, 900);
  };

  const approve = () => {
    if (offline) {
      setQueue((q) => [...q, { ...picked, rate }]);
      onToast({ title: "오프라인 저장됨", desc: `${picked.product_name} · 연결 복구 시 자동 전송` });
    } else {
      const r = onApprove([{ ...picked, rate }]);
      if (r?.escalate) {
        onToast({ title: "점장 결재 요청됨", desc: `${picked.product_name} · ${rate}% (${APPROVAL_THRESHOLD}% 초과)` });
      } else {
        onToast({ title: "ESL 반영 완료", desc: `${picked.product_name} · ${rate}% 할인` });
      }
    }
    setPicked(null);
  };

  const sync = () => {
    setSyncing(true);
    setTimeout(() => {
      onApprove(queue);
      onToast({ title: `${queue.length}건 동기화 완료`, desc: "오프라인 승인 건이 ESL에 반영되었습니다" });
      setQueue([]);
      setSyncing(false);
    }, 1200);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 p-4 backdrop-blur-sm" onClick={onClose}>
      <div className="animate-fade-up w-full max-w-sm" onClick={(e) => e.stopPropagation()}>
        <div className="mb-3 flex items-center justify-between px-1">
          <p className="text-sm font-semibold text-white">현장 PDA 모드</p>
          <button onClick={onClose} className="rounded-lg p-1.5 text-slate-300 transition-colors hover:bg-white/10">
            <X size={18} />
          </button>
        </div>

        {/* 폰 프레임 */}
        <div className="overflow-hidden rounded-[2rem] border-4 border-slate-800 bg-slate-900 shadow-2xl">
          {/* 상태바 */}
          <div className="flex items-center justify-between bg-slate-900 px-5 py-2 text-[10px] text-slate-300">
            <span>18:24</span>
            <div className="flex items-center gap-1.5">
              <Signal size={11} />
              <button onClick={() => setOffline(!offline)} title="연결 상태 전환">
                {offline ? <WifiOff size={11} className="text-brand-400" /> : <Wifi size={11} />}
              </button>
              <Battery size={12} />
            </div>
          </div>

          <div className="min-h-[460px] bg-slate-50">
            {/* 헤더 */}
            <div className="flex items-center gap-2 bg-white px-4 py-3 shadow-sm">
              {picked ? (
                <button onClick={() => setPicked(null)} className="rounded-lg p-1 text-slate-500 hover:bg-slate-100">
                  <ChevronLeft size={18} />
                </button>
              ) : (
                <BrandMark size={18} />
              )}
              <p className="text-sm font-bold">{picked ? "가격 확인" : "FreshWatch 현장"}</p>
              {!picked && (
                <span className="ml-auto rounded-full bg-brand-50 px-2 py-0.5 text-[11px] font-bold text-brand-600">
                  {pending.length}건
                </span>
              )}
            </div>

            {scanning ? (
              <div className="flex h-[400px] flex-col items-center justify-center gap-4">
                <div className="relative flex h-28 w-28 items-center justify-center rounded-2xl border-2 border-dashed border-brand-300">
                  <ScanLine size={40} className="text-brand-500" />
                  <span className="absolute inset-x-3 top-1/2 h-0.5 animate-pulse bg-brand-500" />
                </div>
                <p className="text-sm font-semibold text-slate-600">바코드 인식 중…</p>
              </div>
            ) : picked ? (
              /* ---------- 상품 상세 ---------- */
              <div className="p-4">
                <div className="rounded-2xl bg-white p-4 shadow-sm">
                  <div className="flex items-center gap-2">
                    <p className="text-base font-bold">{picked.product_name}</p>
                    <span className={`rounded-md px-2 py-0.5 text-[11px] font-bold ${
                      picked.days_until_expiry === 0 ? "bg-brand-50 text-brand-600" : "bg-cjorange-50 text-cjorange-700"
                    }`}>
                      {picked.days_until_expiry === 0 ? "D-Day" : `D-${picked.days_until_expiry}`}
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-slate-500">재고 {picked.stock_quantity}개 · 원가 {won(picked.cost)}원</p>

                  <div className="mt-4 rounded-xl bg-slate-50 p-4 text-center">
                    <p className="text-xs text-slate-400 line-through">{won(picked.regular_price)}원</p>
                    <p className="mt-1 text-3xl font-bold tracking-tight text-brand-600">
                      {won(discounted(picked.regular_price, rate / 100))}원
                    </p>
                    <p className="mt-1 text-sm font-bold text-slate-500">{rate}% 할인</p>
                  </div>

                  <div className="mt-3 flex items-center gap-2">
                    <button onClick={() => setRate(Math.max(0, rate - 1))}
                            className="flex-1 rounded-xl border border-slate-200 py-2.5 text-sm font-bold text-slate-600 active:scale-95">
                      −1%
                    </button>
                    <button onClick={() => setRate(Math.min(40, rate + 1))}
                            className="flex-1 rounded-xl border border-slate-200 py-2.5 text-sm font-bold text-slate-600 active:scale-95">
                      +1%
                    </button>
                  </div>

                  <div className="mt-3 rounded-xl border-l-2 border-cjblue-500 bg-cjblue-50 px-3 py-2">
                    <p className="text-[11px] leading-relaxed text-cjblue-800">
                      미판매 시 손실 <b>{man(picked.expected_loss)}만원</b> · 판매확률 <b>{Math.round(picked.sell_probability * 100)}%</b>
                    </p>
                  </div>

                  {!picked.esl_applicable && (
                    <p className="mt-2 rounded-lg bg-violet-50 px-3 py-2 text-[11px] font-medium text-violet-700">
                      ESL 미적용 · 승인 후 라벨 인쇄가 필요합니다
                    </p>
                  )}
                </div>

                <button onClick={approve}
                        className="mt-4 flex w-full items-center justify-center gap-2 rounded-2xl bg-brand-600 py-4 text-base font-bold text-white shadow-lg active:scale-95">
                  <Check size={18} strokeWidth={3} /> {rate > APPROVAL_THRESHOLD ? "점장 결재 요청" : "승인 · ESL 반영"}
                </button>
              </div>
            ) : (
              /* ---------- 스캔 대기 목록 ---------- */
              <div className="p-4">
                {offline && (
                  <div className="mb-3 flex items-center gap-2 rounded-xl bg-slate-900 px-3 py-2.5 text-white">
                    <WifiOff size={14} className="shrink-0 text-brand-400" />
                    <p className="flex-1 text-[11px] leading-relaxed">
                      오프라인 · 승인은 기기에 저장되고 연결 복구 시 자동 전송됩니다
                    </p>
                  </div>
                )}
                {queue.length > 0 && (
                  <button onClick={sync} disabled={offline || syncing}
                          className="mb-3 flex w-full items-center justify-center gap-2 rounded-xl bg-cjblue-600 py-3 text-sm font-bold text-white disabled:opacity-50">
                    {syncing ? <Loader2 size={15} className="animate-spin" /> : <CloudUpload size={15} />}
                    {syncing ? "동기화 중" : offline ? `대기 ${queue.length}건 · 연결 필요` : `대기 ${queue.length}건 동기화`}
                  </button>
                )}
                <button onClick={() => pending[0] && scan(pending[0])}
                        disabled={pending.length === 0}
                        className="flex w-full items-center justify-center gap-2 rounded-2xl bg-slate-900 py-4 text-sm font-bold text-white active:scale-95 disabled:opacity-40">
                  <ScanLine size={18} /> 바코드 스캔
                </button>

                <p className="mb-2 mt-5 text-xs font-semibold text-slate-500">주변 폐기위험 상품</p>
                <div className="space-y-2">
                  {pending.length === 0 ? (
                    <div className="rounded-2xl bg-white p-6 text-center shadow-sm">
                      <p className="text-sm font-semibold text-slate-700">처리 완료</p>
                      <p className="mt-1 text-xs text-slate-400">모든 상품이 승인되었습니다.</p>
                    </div>
                  ) : (
                    pending.slice(0, 5).map((i) => (
                      <button key={i.product_id} onClick={() => scan(i)}
                              className="flex w-full items-center gap-3 rounded-2xl bg-white p-3 text-left shadow-sm active:scale-95">
                        <span className={`h-9 w-1 rounded-full ${
                          i.days_until_expiry === 0 ? "bg-brand-500" : i.days_until_expiry === 1 ? "bg-cjorange-400" : "bg-slate-300"
                        }`} />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-sm font-semibold">{i.product_name}</span>
                          <span className="block text-[11px] text-slate-400">재고 {i.stock_quantity}개 · 손실 {man(i.expected_loss)}만원</span>
                        </span>
                        <span className="shrink-0 rounded-lg bg-brand-50 px-2 py-1 text-xs font-bold text-brand-600">
                          −{Math.round(i.recommended_rate * 100)}%
                        </span>
                      </button>
                    ))
                  )}
                </div>
              </div>
            )}
          </div>
        </div>

        <p className="mt-3 px-1 text-center text-[11px] text-slate-400">
          현장 담당자가 매대에서 상품을 스캔해 즉시 가격을 확인·승인하는 모바일 화면입니다.
        </p>
      </div>
    </div>
  );
}
