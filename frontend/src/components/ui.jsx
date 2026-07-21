import { useEffect, useRef, useState } from "react";
import { BRAND } from "../lib/brand";

/* ---------- 브랜드 심볼 ----------
   public/lotte-mart.png 이 있으면 그 이미지를, 없으면 내장 심볼을 표시합니다. */
export function BrandMark({ size = 22, className = "", plate = false }) {
  const [useImg, setUseImg] = useState(true);
  const src = (import.meta.env.BASE_URL || "/") + (BRAND.clientLogo || "");

  if (useImg && BRAND.clientLogo) {
    const img = (
      <img
        src={src}
        alt=""
        width={size}
        height={size}
        onError={() => setUseImg(false)}
        className={`shrink-0 object-contain ${className}`}
        aria-hidden="true"
      />
    );
    /* 어두운 배경에서 로고 테두리가 뭉개지지 않도록 흰 배경판을 깝니다 */
    return plate ? (
      <span
        className="flex shrink-0 items-center justify-center rounded-[9px] bg-white"
        style={{ width: size + 8, height: size + 8 }}
      >
        {img}
      </span>
    ) : (
      img
    );
  }
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" className={`shrink-0 ${className}`} aria-hidden="true">
      <path
        d="M32 4 C 38 4 42 6 46.5 10.5 L 53.5 17.5 C 58 22 60 26 60 32 C 60 38 58 42 53.5 46.5 L 46.5 53.5 C 42 58 38 60 32 60 C 26 60 22 58 17.5 53.5 L 10.5 46.5 C 6 42 4 38 4 32 C 4 26 6 22 10.5 17.5 L 17.5 10.5 C 22 6 26 4 32 4 Z"
        fill="#ED1B2F"
      />
      <path
        d="M44.5 38.5 C 42.6 44.2 37.6 47.6 33.6 44.8 C 29.6 42 26.9 34.6 26.3 27.6 C 25.7 20.5 27.8 14.4 32.2 14.4 C 36.6 14.4 38.9 20.4 37.2 27.2 C 35.4 34.4 31.8 40.6 31 45.4"
        fill="none" stroke="#fff" strokeWidth="4.1" strokeLinecap="round" strokeLinejoin="round"
      />
      <circle cx="23.4" cy="45.2" r="2.9" fill="#fff" />
    </svg>
  );
}

/* ---------- 스켈레톤 ---------- */
export function Skeleton({ className = "" }) {
  return <div className={`animate-pulse rounded-lg bg-slate-200/70 ${className}`} />;
}

/* ---------- 패널 ---------- */
export function Panel({ title, right, children, className = "", padded = true }) {
  return (
    <section className={`rounded-2xl border border-slate-200 bg-white shadow-sm ${padded ? "p-5" : ""} ${className}`}>
      {(title || right) && (
        <header className={`mb-4 flex items-center justify-between ${padded ? "" : "px-5 pt-5"}`}>
          <h3 className="text-sm font-semibold text-slate-900">{title}</h3>
          {right}
        </header>
      )}
      {children}
    </section>
  );
}

/* ---------- KPI 카드 ---------- */
export function Kpi({ label, value, unit, sub, tone = "plain", icon: Icon, index = 0, loading }) {
  const tones = {
    plain: "bg-white border-slate-200",
    danger: "bg-brand-50 border-brand-100",
    ok: "bg-emerald-50 border-emerald-100",
  };
  const t = {
    plain: { l: "text-slate-500", v: "text-slate-900", s: "text-slate-400", i: "text-slate-200" },
    danger: { l: "text-brand-600", v: "text-brand-600", s: "text-brand-500", i: "text-brand-200" },
    ok: { l: "text-emerald-700", v: "text-emerald-700", s: "text-emerald-600", i: "text-emerald-200" },
  }[tone];

  if (loading)
    return (
      <div className="rounded-2xl border border-slate-200 bg-white p-5">
        <Skeleton className="h-3 w-16" />
        <Skeleton className="mt-3 h-8 w-24" />
        <Skeleton className="mt-2 h-3 w-32" />
      </div>
    );

  return (
    <div
      className={`animate-fade-up relative overflow-hidden rounded-2xl border p-5 shadow-sm transition-all duration-300 hover:-translate-y-0.5 hover:shadow-md ${tones[tone]}`}
      style={{ animationDelay: `${index * 80}ms` }}
    >
      {Icon && <Icon size={46} className={`absolute -right-2 -top-2 ${t.i}`} strokeWidth={1.5} />}
      <p className={`text-xs font-medium ${t.l}`}>{label}</p>
      <p className={`mt-2 text-3xl font-bold tracking-tight ${t.v}`}>
        <CountUp value={value} />
        {unit && <span className="ml-1 text-sm font-semibold">{unit}</span>}
      </p>
      {sub && <p className={`mt-1 text-xs ${t.s}`}>{sub}</p>}
    </div>
  );
}

/* ---------- 숫자 카운트업 ---------- */
export function CountUp({ value, duration = 700 }) {
  const num = typeof value === "number" ? value : parseFloat(String(value).replace(/,/g, ""));
  const [n, setN] = useState(0);
  const prev = useRef(0);
  const decimals = String(value).includes(".") ? 1 : 0;

  useEffect(() => {
    if (isNaN(num)) return;
    const from = prev.current;
    let raf, start;
    const step = (ts) => {
      if (!start) start = ts;
      const p = Math.min((ts - start) / duration, 1);
      const eased = 1 - Math.pow(1 - p, 3);
      setN(from + (num - from) * eased);
      if (p < 1) raf = requestAnimationFrame(step);
      else prev.current = num;
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [num, duration]);

  if (isNaN(num)) return <>{value}</>;
  return <>{n.toLocaleString("ko-KR", { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}</>;
}

/* ---------- D-day 태그 ---------- */
export function DayTag({ d }) {
  const map = {
    0: "bg-brand-50 text-brand-600 ring-brand-200",
    1: "bg-amber-50 text-amber-700 ring-amber-200",
    2: "bg-slate-100 text-slate-600 ring-slate-200",
  };
  return (
    <span className={`shrink-0 rounded-md px-2 py-0.5 text-[11px] font-bold ring-1 ${map[d] ?? map[2]}`}>
      {d === 0 ? "D-Day" : `D-${d}`}
    </span>
  );
}

export function UrgencyBar({ d }) {
  const c = d === 0 ? "bg-brand-500" : d === 1 ? "bg-amber-400" : "bg-slate-300";
  return <span className={`h-9 w-1 shrink-0 rounded-full ${c}`} />;
}

/* ---------- 버튼 ---------- */
export function Button({ variant = "ghost", className = "", children, ...props }) {
  const base = "inline-flex items-center justify-center gap-1.5 rounded-xl text-sm font-semibold transition-all active:scale-95 disabled:pointer-events-none disabled:opacity-40";
  const styles = {
    primary: "bg-brand-600 text-white shadow-sm hover:bg-brand-700 hover:shadow px-5 py-2.5",
    ghost: "border border-slate-200 bg-white text-slate-600 hover:bg-slate-50 px-4 py-2.5",
    small: "border border-slate-200 bg-white text-slate-600 hover:bg-slate-50 px-3 py-1.5 text-xs",
  };
  return (
    <button className={`${base} ${styles[variant]} ${className}`} {...props}>
      {children}
    </button>
  );
}

/* ---------- 빈 상태 ---------- */
export function Empty({ icon: Icon, title, desc }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      {Icon && <Icon size={40} className="mb-3 text-slate-300" strokeWidth={1.5} />}
      <p className="text-sm font-semibold text-slate-700">{title}</p>
      {desc && <p className="mt-1 text-xs text-slate-400">{desc}</p>}
    </div>
  );
}

/* ---------- 에러 ---------- */
export function ErrorBox({ message, onRetry }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-2xl border border-brand-100 bg-brand-50 py-14 text-center">
      <p className="text-sm font-semibold text-brand-700">데이터를 불러오지 못했습니다</p>
      <p className="mt-1 text-xs text-brand-500">{message}</p>
      {onRetry && (
        <Button variant="small" className="mt-4" onClick={onRetry}>
          다시 시도
        </Button>
      )}
    </div>
  );
}

/* ---------- 토스트 ---------- */
export function Toast({ show, tone = "ok", title, desc }) {
  if (!show) return null;
  const dot = tone === "ok" ? "bg-emerald-500" : "bg-brand-500";
  return (
    <div className="animate-slide-in fixed bottom-8 left-1/2 z-50 flex max-w-[92vw] items-center gap-3 rounded-2xl bg-slate-900 px-5 py-3.5 text-sm text-white shadow-2xl">
      <span className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full ${dot}`}>
        <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="none" stroke="white" strokeWidth="3.5" strokeLinecap="round" strokeLinejoin="round">
          <polyline points="20 6 9 17 4 12" />
        </svg>
      </span>
      <span>
        <b className="font-semibold">{title}</b>
        {desc && <span className="ml-1.5 text-slate-300">{desc}</span>}
      </span>
    </div>
  );
}

/* ---------- 데이터 로딩 훅 ---------- */
export function useAsync(fn, deps = []) {
  const [state, setState] = useState({ data: null, loading: true, error: null });
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let alive = true;
    setState((s) => ({ ...s, loading: true, error: null }));
    fn()
      .then((d) => alive && setState({ data: d, loading: false, error: null }))
      .catch((e) => alive && setState({ data: null, loading: false, error: e.message }));
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  return { ...state, reload: () => setTick((t) => t + 1) };
}
