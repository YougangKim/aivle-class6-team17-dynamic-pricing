import { useState, useMemo } from "react";
import { X, Loader2, Check, ShieldCheck, Clock, Bell, Activity, AlertTriangle, RotateCcw } from "lucide-react";
import { Button } from "./ui";
import { DEFAULT_POLICY, savePolicy, previewPolicyImpact } from "../lib/api";

function Field({ label, desc, children }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 py-3.5 last:border-0">
      <div className="min-w-0">
        <p className="text-sm font-semibold">{label}</p>
        {desc && <p className="mt-0.5 text-xs text-slate-400">{desc}</p>}
      </div>
      {children}
    </div>
  );
}

function Stepper({ value, onChange, min = 0, max = 40, step = 1, unit = "%" }) {
  return (
    <div className="flex items-center gap-2">
      <span className="w-14 text-right text-base font-bold">{value}{unit}</span>
      <span className="inline-flex overflow-hidden rounded-lg border border-slate-200">
        <button onClick={() => onChange(Math.max(min, value - step))} className="px-2.5 py-1 text-slate-500 hover:bg-slate-100">−</button>
        <button onClick={() => onChange(Math.min(max, value + step))} className="border-l border-slate-200 px-2.5 py-1 text-slate-500 hover:bg-slate-100">+</button>
      </span>
    </div>
  );
}

function Toggle({ on, onChange }) {
  return (
    <button onClick={() => onChange(!on)}
            className={`relative h-6 w-11 rounded-full transition-colors ${on ? "bg-brand-600" : "bg-slate-200"}`}>
      <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-all ${on ? "left-5" : "left-0.5"}`} />
    </button>
  );
}

export default function SettingsModal({ storeId, policy, onSaved, onClose, onToast }) {
  const [p, setP] = useState(policy ?? DEFAULT_POLICY);
  const [saving, setSaving] = useState(false);
  const set = (k, v) => setP({ ...p, [k]: v });

  /* 슬라이더를 움직일 때마다 이 설정이 대기열에 어떤 영향을 주는지 즉시 계산합니다 */
  const impact = useMemo(() => previewPolicyImpact(storeId, p), [storeId, p]);
  const man = (v) => (v / 10000).toFixed(1);

  const save = async () => {
    setSaving(true);
    await savePolicy(storeId, p);
    setSaving(false);
    onSaved?.(p);
    onToast({
      title: "정책 저장 · AI 추천 재계산 완료",
      desc: `대기 ${impact.pending}건 · 추천 ${impact.pending ? `${impact.minRate}~${impact.maxRate}%` : "없음"} · 점장 결재 ${impact.escalate}건`,
    });
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-slate-900/50 backdrop-blur-sm sm:items-center sm:p-6" onClick={onClose}>
      <div className="animate-fade-up max-h-[88vh] w-full max-w-xl overflow-y-auto rounded-t-3xl bg-white shadow-2xl sm:rounded-3xl" onClick={(e) => e.stopPropagation()}>
        <div className="sticky top-0 flex items-start justify-between border-b border-slate-100 bg-white/95 px-6 py-5 backdrop-blur">
          <div>
            <h2 className="text-lg font-bold tracking-tight">할인 정책 설정</h2>
            <p className="mt-0.5 text-xs text-slate-500">본사 지침을 시스템에 반영합니다. AI는 이 범위 안에서만 추천합니다.</p>
          </div>
          <button onClick={onClose} className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100"><X size={18} /></button>
        </div>

        {/* ── 실시간 영향 미리보기 ─────────────────────────────
            상한을 낮추면 무슨 일이 벌어지는지 저장 전에 보여줍니다.
            이 패널이 없으면 "상한 20%" 저장 후 대기열이 왜 줄었는지 알 수 없습니다. */}
        <div className="sticky top-[89px] z-10 border-b border-slate-100 bg-slate-50/95 px-6 py-4 backdrop-blur">
          <p className="mb-2.5 flex items-center gap-1.5 text-xs font-bold text-slate-500">
            <Activity size={13} className="text-cjblue-600" /> 이 설정을 저장하면 — 오늘 {storeId} 대기열 기준
          </p>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <div className="rounded-xl bg-white px-3 py-2.5 ring-1 ring-slate-200">
              <p className="text-[11px] text-slate-500">승인 대기</p>
              <p className="mt-0.5 text-lg font-bold leading-tight">
                {impact.pending}<span className="ml-0.5 text-[11px] font-semibold text-slate-400">/ {impact.total}건</span>
              </p>
              {impact.dropped > 0 && (
                <p className="text-[10px] font-medium text-cjorange-600">{impact.dropped}건은 할인해도 손해</p>
              )}
            </div>
            <div className="rounded-xl bg-white px-3 py-2.5 ring-1 ring-slate-200">
              <p className="text-[11px] text-slate-500">추천 할인율</p>
              <p className="mt-0.5 text-lg font-bold leading-tight">
                {impact.pending ? `${impact.minRate}~${impact.maxRate}` : "—"}<span className="text-[11px]">%</span>
              </p>
              {impact.capped > 0 && (
                <p className="text-[10px] font-medium text-cjorange-600">{impact.capped}건이 상한에 걸림</p>
              )}
            </div>
            <div className="rounded-xl bg-white px-3 py-2.5 ring-1 ring-slate-200">
              <p className="text-[11px] text-slate-500">점장 결재</p>
              <p className="mt-0.5 text-lg font-bold leading-tight">
                {impact.escalate}<span className="ml-0.5 text-[11px] font-semibold text-slate-400">건</span>
              </p>
              <p className="text-[10px] text-slate-400">{p.two_step_over}% 초과분</p>
            </div>
            <div className="rounded-xl bg-white px-3 py-2.5 ring-1 ring-slate-200">
              <p className="text-[11px] text-slate-500">미조치 대비 순이익</p>
              <p className={`mt-0.5 text-lg font-bold leading-tight ${impact.gain >= 0 ? "text-emerald-600" : "text-brand-600"}`}>
                +{man(impact.gain)}<span className="text-[11px]">만원</span>
              </p>
              {Math.abs(impact.gainDelta) >= 5000 && (
                <p className={`text-[10px] font-medium ${impact.gainDelta < 0 ? "text-brand-600" : "text-emerald-600"}`}>
                  기본 정책 대비 {impact.gainDelta > 0 ? "+" : ""}{man(impact.gainDelta)}만원
                </p>
              )}
            </div>
          </div>

          {impact.approvalMoot && (
            <p className="mt-2.5 flex items-start gap-1.5 rounded-xl bg-cjorange-50 px-3 py-2 text-[11px] leading-relaxed text-cjorange-800">
              <AlertTriangle size={13} className="mt-px shrink-0" />
              <span>
                결재 임계값 <b>{p.two_step_over}%</b>가 도달 가능한 최대 할인율 <b>{impact.maxReachable}%</b> 이상이라,
                <b> 점장 최종 승인이 구조적으로 발생하지 않습니다.</b> 2단 결재를 쓰시려면 임계값을 낮추거나 잔여일별 상한을 올리세요.
              </span>
            </p>
          )}
          {!impact.approvalMoot && impact.gainDelta < -10000 && (
            <p className="mt-2.5 flex items-start gap-1.5 rounded-xl bg-brand-50 px-3 py-2 text-[11px] leading-relaxed text-brand-700">
              <AlertTriangle size={13} className="mt-px shrink-0" />
              <span>
                기본 정책보다 순이익이 <b>{man(-impact.gainDelta)}만원</b> 낮습니다.
                상한이 낮아 AI가 최적 할인율까지 내리지 못하고 있습니다.
              </span>
            </p>
          )}
        </div>

        <div className="px-6 py-4">
          <p className="mb-1 flex items-center gap-1.5 text-xs font-bold text-slate-500">
            <ShieldCheck size={13} className="text-brand-600" /> 할인 한도
          </p>
          <Field label="최대 할인율" desc="본사 지침 상한 · 초과 필요 시 폐기 전환">
            <Stepper value={p.max_discount} onChange={(v) => set("max_discount", v)} min={10} max={70} />
          </Field>
          <p className="pt-1 text-[11px] leading-relaxed text-slate-400">
            AI는 아래 잔여일별 상한 안에서 <b className="text-slate-500">1%p 단위로 자유롭게</b> 추천합니다.
            고정 할인율이 아니라 순이익이 최대가 되는 지점을 상품마다 계산합니다.
          </p>
          <Field label="D-2 할인 상한"><Stepper value={p.step_d2} onChange={(v) => set("step_d2", v)} max={p.max_discount} /></Field>
          <Field label="D-1 할인 상한"><Stepper value={p.step_d1} onChange={(v) => set("step_d1", v)} max={p.max_discount} /></Field>
          <Field label="D-Day 할인 상한"><Stepper value={p.step_d0} onChange={(v) => set("step_d0", v)} max={p.max_discount} /></Field>

          <p className="mb-1 mt-5 flex items-center gap-1.5 text-xs font-bold text-slate-500">
            <Clock size={13} className="text-cjorange-600" /> 운영 시간
          </p>
          <Field label="마감 할인 시작" desc="이 시각 이후 D-Day 상품에 상한 할인 적용">
            <Stepper value={p.closing_hour} onChange={(v) => set("closing_hour", v)} min={16} max={23} step={1} unit="시" />
          </Field>
          <Field label="2단 결재 임계값" desc="이 할인율을 초과하면 담당자 승인 후 점장 최종 승인이 필요합니다">
            <Stepper value={p.two_step_over} onChange={(v) => set("two_step_over", v)} max={p.max_discount} />
          </Field>
          <Field label="자동 승인 임계값" desc="이 할인율 이하는 승인 없이 자동 반영 (0 = 사용 안 함)">
            <Stepper value={p.auto_approve_under} onChange={(v) => set("auto_approve_under", v)} max={p.max_discount} />
          </Field>

          <p className="mb-1 mt-5 flex items-center gap-1.5 text-xs font-bold text-slate-500">
            <Bell size={13} className="text-cjblue-600" /> 알림
          </p>
          <Field label="ESL 전송 실패 알림">
            <Toggle on={p.notify_esl_fail} onChange={(v) => set("notify_esl_fail", v)} />
          </Field>
          <Field label="신규 폐기위험 탐지 알림">
            <Toggle on={p.notify_new_risk} onChange={(v) => set("notify_new_risk", v)} />
          </Field>

          <p className="mt-5 rounded-xl bg-slate-50 px-4 py-3 text-[11px] leading-relaxed text-slate-500">
            현재 설정은 <b className="text-slate-700">{storeId}</b> 점포에만 적용됩니다.
            전 점포 일괄 적용은 본사 계정에서만 가능합니다.
          </p>
        </div>

        <div className="sticky bottom-0 flex justify-end gap-2 border-t border-slate-100 bg-white/95 px-6 py-4 backdrop-blur">
          <Button onClick={() => setP(DEFAULT_POLICY)}>
            <RotateCcw size={14} /> 권장 정책으로 (40 / 35 / 25)
          </Button>
          <Button variant="primary" onClick={save} disabled={saving}>
            {saving ? <Loader2 size={15} className="animate-spin" /> : <Check size={15} />}
            {saving ? "저장 중" : "저장"}
          </Button>
        </div>
      </div>
    </div>
  );
}
