import { useState } from "react";
import { X, Loader2, Check, ShieldCheck, Clock, Bell } from "lucide-react";
import { Button } from "./ui";
import { DEFAULT_POLICY, savePolicy } from "../lib/api";

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

export default function SettingsModal({ storeId, onClose, onToast }) {
  const [p, setP] = useState(DEFAULT_POLICY);
  const [saving, setSaving] = useState(false);
  const set = (k, v) => setP({ ...p, [k]: v });

  const save = async () => {
    setSaving(true);
    await savePolicy(storeId, p);
    setSaving(false);
    onToast({ title: "정책 저장 완료", desc: "다음 배치부터 적용됩니다" });
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

        <div className="px-6 py-4">
          <p className="mb-1 flex items-center gap-1.5 text-xs font-bold text-slate-500">
            <ShieldCheck size={13} className="text-brand-600" /> 할인 한도
          </p>
          <Field label="최대 할인율" desc="본사 지침 상한 · 초과 필요 시 폐기 전환">
            <Stepper value={p.max_discount} onChange={(v) => set("max_discount", v)} min={10} max={70} />
          </Field>
          <Field label="D-2 기본 할인율"><Stepper value={p.step_d2} onChange={(v) => set("step_d2", v)} max={p.max_discount} /></Field>
          <Field label="D-1 기본 할인율"><Stepper value={p.step_d1} onChange={(v) => set("step_d1", v)} max={p.max_discount} /></Field>
          <Field label="D-Day 기본 할인율"><Stepper value={p.step_d0} onChange={(v) => set("step_d0", v)} max={p.max_discount} /></Field>

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
          <Button onClick={() => setP(DEFAULT_POLICY)}>기본값 복원</Button>
          <Button variant="primary" onClick={save} disabled={saving}>
            {saving ? <Loader2 size={15} className="animate-spin" /> : <Check size={15} />}
            {saving ? "저장 중" : "저장"}
          </Button>
        </div>
      </div>
    </div>
  );
}
