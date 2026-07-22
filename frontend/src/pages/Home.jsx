import { useState, useMemo, useEffect } from "react";
import {
  Tag, AlertTriangle, Wallet, Trash2, Check, Minus, Plus,
  LineChart as LineIcon, Loader2, PartyPopper, CloudRain, Clock, MoonStar, EyeOff, ChevronDown,
  Timer, Zap, ArrowDownWideNarrow, CalendarOff, ShieldCheck, UserCheck, X,
} from "lucide-react";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Cell,
  ComposedChart, Line, Area, ReferenceLine, ReferenceArea, Legend,
} from "recharts";
import { Panel, Kpi, DayTag, UrgencyBar, Skeleton, ErrorBox, Empty, Button, useAsync } from "../components/ui";
import DetailModal from "../components/DetailModal";
import { getSummary, getRecommendations, approve, getSkipped, APPROVAL_THRESHOLD } from "../lib/api";
import { won, man, discounted } from "../lib/format";

const tip = { borderRadius: 12, border: "1px solid #cbd5e1", fontSize: 12, boxShadow: "0 4px 14px rgba(0,0,0,.10)", background: "#ffffff", color: "#0f172a" };

const FILTERS = [
  { key: "all", label: "전체" }, { key: "d0", label: "D-Day" }, { key: "d1", label: "D-1" }, { key: "d2", label: "D-2" },
  { key: "축산", label: "축산" }, { key: "수산", label: "수산" }, { key: "청과", label: "청과" },
  { key: "유제품", label: "유제품" }, { key: "즉석", label: "즉석" },
];

function Row({ item, selected, onToggle, rate, onRate, onOpen }) {
  const recRate = Math.round(item.recommended_rate * 100);
  const price = discounted(item.regular_price, rate / 100);

  return (
    <div className={`border-b border-slate-100 px-5 py-4 transition-all last:border-0 ${selected ? "bg-brand-50/60" : "hover:bg-slate-50"}`}>
      <div className="flex items-start gap-4">
        <button onClick={onToggle} aria-label="선택"
          className={`mt-1 flex h-5 w-5 shrink-0 items-center justify-center rounded-md border transition-all ${
            selected ? "scale-105 border-brand-600 bg-brand-600" : "border-slate-300 bg-white hover:border-slate-400"
          }`}>
          {selected && <Check size={13} className="text-white" strokeWidth={3.5} />}
        </button>

        <UrgencyBar d={item.days_until_expiry} />

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-bold">{item.product_name}</span>
            <DayTag d={item.days_until_expiry} />
            <span className="rounded-md bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-500">{item.category}</span>
            {!item.esl_applicable && (
              <span className="rounded-md bg-violet-50 px-2 py-0.5 text-[11px] font-semibold text-violet-700 ring-1 ring-violet-200">수기 라벨</span>
            )}
          </div>
          <p className="mt-1 text-xs text-slate-500">
            재고 {item.stock_quantity}개 · 원가 {won(item.cost)}원 · 미판매 시 손실{" "}
            <b className="font-semibold text-brand-600">{man(item.expected_loss)}만원</b>
          </p>
          <button onClick={onOpen} className="mt-2 inline-flex items-center gap-1 text-xs font-semibold text-cjblue-600 hover:text-cjblue-700">
            <LineIcon size={12} /> AI 추천 근거 · 손익 시뮬레이션
          </button>
        </div>

        <div className="shrink-0 text-right">
          <p className="text-xs text-slate-400 line-through">{won(item.regular_price)}원</p>
          <p className="text-lg font-bold tracking-tight">
            {won(price)}<span className="ml-1.5 text-xs font-bold text-brand-600">−{rate}%</span>
          </p>
          <div className="mt-1.5 inline-flex overflow-hidden rounded-lg border border-slate-200">
            <button onClick={() => onRate(Math.max(0, rate - 1))} disabled={rate <= 0}
                    className="px-2 py-1 text-slate-500 transition-colors hover:bg-slate-100 disabled:opacity-30"><Minus size={13} /></button>
            <button onClick={() => onRate(Math.min(40, rate + 1))} disabled={rate >= 40}
                    className="border-l border-slate-200 px-2 py-1 text-slate-500 transition-colors hover:bg-slate-100 disabled:opacity-30"><Plus size={13} /></button>
          </div>
          {rate !== recRate && <p className="mt-1 text-[11px] font-medium text-cjorange-600">추천 {recRate}%에서 조정</p>}
          {rate > APPROVAL_THRESHOLD && (
            <p className="mt-1 flex items-center justify-end gap-1 text-[11px] font-semibold text-brand-600">
              <ShieldCheck size={11} /> 점장 승인 필요
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

export default function Home({ storeId, onToast, approved, onApprove, rates, setRates, onItemsLoaded, role, pendingMgr, onMgrDecision }) {
  const s = useAsync(() => getSummary(storeId), [storeId]);
  const r = useAsync(() => getRecommendations(storeId), [storeId]);
  const [filter, setFilter] = useState("all");
  const [sel, setSel] = useState(null);
  const [sending, setSending] = useState(false);
  const [detail, setDetail] = useState(null);
  const [showSkipped, setShowSkipped] = useState(false);
  const skipped = useAsync(() => getSkipped(storeId), [storeId]);

  /* ---- 매장 시계 : 대한민국 표준시(KST) 실시간 동기화 ---- */
  const CLOSE_MIN = 22 * 60;
  const kstNow = () => {
    const t = new Date().toLocaleString("en-US", {
      timeZone: "Asia/Seoul", hour12: false, hour: "2-digit", minute: "2-digit",
    });
    const [h, m] = t.split(":").map(Number);
    return (h % 24) * 60 + m;
  };
  const kstSec = () =>
    Number(new Date().toLocaleString("en-US", { timeZone: "Asia/Seoul", second: "2-digit" }));

  const [clock, setClock] = useState(kstNow);
  const [sec, setSec] = useState(kstSec);
  const [demo, setDemo] = useState(false);          // 시연용 가속 (1초 = 1분)
  const [manualClosing, setManualClosing] = useState(false);

  useEffect(() => {
    const t = setInterval(() => {
      if (demo) {
        setClock((c) => Math.min(c + 1, CLOSE_MIN));
        setSec(0);
      } else {
        setClock(kstNow());
        setSec(kstSec());
      }
    }, 1000);
    return () => clearInterval(t);
  }, [demo]);

  const remain = Math.max(CLOSE_MIN - clock, 0);
  const hh = String(Math.floor(clock / 60)).padStart(2, "0");
  const mm = String(clock % 60).padStart(2, "0");
  const closingMode = manualClosing || remain <= 240;

  /* 시간이 갈수록 추천 상향: 마감 3시간 전부터 1시간마다 +5%p */
  const escalation = Math.min(Math.max(Math.floor((180 - remain) / 60) + 1, 0), 3) * 5;
  const nextStepIn = remain > 0 ? remain % 60 || 60 : 0;
  const canApprove = !!role?.canPolicy;
  const closingRate = (i) => Math.min(40, Math.round(i.recommended_rate * 100) + (i.days_until_expiry === 0 ? escalation : 0));

  const all = r.data ?? [];
  useEffect(() => { if (r.data) onItemsLoaded(r.data); }, [r.data]); // eslint-disable-line
  const pending = all.filter((i) => !approved.has(i.product_id) && !pendingMgr.has(i.product_id));
  const selected = sel ?? new Set(pending.map((i) => i.product_id));
  const rateOf = (i) => rates[i.product_id] ?? (closingMode ? closingRate(i) : Math.round(i.recommended_rate * 100));
  const d = s.data;
  const cal = d?.calendar;

  /* ---- 승인 상태가 반영된 실시간 KPI ---- */
  const kpi = useMemo(() => {
    const risk = pending.reduce((sum, i) => sum + i.expected_loss, 0);
    let revenue = 0, residual = 0;
    all.forEach((i) => {
      const a = approved.get(i.product_id);
      if (a) {
        const sold = i.stock_quantity * i.sell_probability;
        revenue += sold * discounted(i.regular_price, a.rate / 100);
        residual += (i.stock_quantity - sold) * i.cost;
      } else {
        residual += i.expected_loss;
      }
    });
    const byCat = Object.entries(
      pending.reduce((a, i) => ({ ...a, [i.category]: (a[i.category] || 0) + i.expected_loss }), {})
    ).map(([name, value]) => ({ name, value: +(value / 10000).toFixed(1) })).sort((a, b) => b.value - a.value);
    return { risk, revenue, residual, byCat, baseRisk: all.reduce((s2, i) => s2 + i.expected_loss, 0) };
  }, [all, approved, pending]);

  /* 손실 흐름(워터폴) — risk = 회수 + 잔여 */
  const waterfall = useMemo(() => {
    const risk = kpi.baseRisk / 10000;
    const residual = kpi.residual / 10000;
    const recovered = Math.max(risk - residual, 0);
    return [
      { name: "오늘 폐기 위험", base: 0, val: +risk.toFixed(1), color: "#E4002B" },
      { name: "추천 적용 회수", base: +residual.toFixed(1), val: +recovered.toFixed(1), color: "#059669" },
      { name: "잔여 폐기손실", base: 0, val: +residual.toFixed(1), color: "#cbd5e1" },
    ];
  }, [kpi]);

  /* 마감까지 소진 예측 */
  const closingHour = 22;
  const nowHour = d ? parseInt(d.context.store_time.split(":")[0], 10) : 18;
  const nowLabel = `${nowHour}시`;
  const totalStock = pending.reduce((sum, i) => sum + i.stock_quantity, 0);
  const sellCurve = useMemo(() => {
    const hours = [];
    for (let h = 9; h <= closingHour; h++) {
      const t = (h - 9) / (closingHour - 9);
      const noDisc = totalStock * 0.42 * Math.pow(t, 1.15);
      const boost = h >= nowHour ? Math.min((h - nowHour) * 0.09, 0.42) : 0;
      const withDisc = totalStock * (0.42 + boost) * Math.pow(t, 1.05);
      hours.push({
        label: `${h}시`,
        "할인 미적용": Math.round(noDisc),
        "추천 적용": Math.round(withDisc),
        추가판매: Math.round(withDisc - noDisc),
      });
    }
    return hours;
  }, [totalStock, nowHour]);
  const extraSold = sellCurve.length ? sellCurve[sellCurve.length - 1].추가판매 : 0;

  const shown = useMemo(() => {
    let list = pending;
    if (filter !== "all") {
      list = filter.startsWith("d")
        ? pending.filter((i) => i.days_until_expiry === +filter[1])
        : pending.filter((i) => i.category === filter);
    }
    if (closingMode) {
      list = [...list].sort((a, b) =>
        a.days_until_expiry - b.days_until_expiry || b.expected_loss - a.expected_loss
      );
    }
    return list;
  }, [pending, filter, closingMode]);

  const toggle = (id) => {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id); else next.add(id);
    setSel(next);
  };

  const applyClosingAll = async () => {
    const targets = pending.filter((i) => i.days_until_expiry === 0);
    if (targets.length === 0) return;
    setSending(true);
    try {
      const payload = targets.map((i) => ({ product_id: i.product_id, approved_rate: 0.4, recommended_rate: i.recommended_rate }));
      await approve(storeId, payload);
      const r = onApprove(targets.map((i) => ({ ...i, rate: 40 })));
      onToast({
        title: `D-Day ${targets.length}건 상한 적용`,
        desc: r?.escalate ? `40% 할인 ${r.escalate}건은 점장 최종 승인 대기` : "ESL 전송 요청됨",
      });
    } catch (e) {
      onToast({ tone: "error", title: "적용 실패", desc: e.message });
    }
    setSending(false);
  };

  const submit = async () => {
    setSending(true);
    try {
      const targets = pending.filter((i) => selected.has(i.product_id));
      const payload = targets.map((i) => ({
        product_id: i.product_id, approved_rate: rateOf(i) / 100, recommended_rate: i.recommended_rate,
      }));
      await approve(storeId, payload);
      const r = onApprove(targets.map((i) => ({ ...i, rate: rateOf(i) })));
      setSel(null);
      if (r?.escalate) {
        onToast({
          title: `${r.direct}건 승인 완료 · ${r.escalate}건 점장 결재 요청`,
          desc: `${APPROVAL_THRESHOLD}% 초과 할인은 점장 최종 승인 후 반영됩니다`,
        });
      } else {
        onToast({ title: `${r?.direct ?? targets.length}건 승인 완료`, desc: "ESL 전송 요청됨" });
      }
    } catch (e) {
      onToast({ tone: "error", title: "승인 실패", desc: e.message });
    }
    setSending(false);
  };

  if (s.error) return <ErrorBox message={s.error} onRetry={s.reload} />;

  const loading = s.loading || r.loading;
  const cutRate = kpi.baseRisk ? Math.round((1 - kpi.risk / kpi.baseRisk) * 100) : 0;

  return (
    <div className="space-y-6">
      {d && (
        <div className="flex flex-wrap items-center gap-x-5 gap-y-2 rounded-2xl border border-slate-200 bg-white px-5 py-3 text-xs">
          <span className="flex items-center gap-1.5 font-semibold text-brand-600">
            <span className="relative flex h-2 w-2">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-brand-400 opacity-75" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-brand-500" />
            </span>
            LIVE · 실시간 탐지
          </span>
          <span className="flex items-center gap-1.5 text-slate-500">
            <CloudRain size={13} className="text-cjblue-600" />
            서울 {d.context.weather} · {d.context.temp}°C · 방문객 {Math.round(d.context.visitor_delta * 100)}%
          </span>
          <span className="flex items-center gap-1.5 text-slate-500">
            <Clock size={13} /> 매장시간 <b className="font-mono font-semibold text-slate-700">{hh}:{mm}</b>
            <span className="text-[10px] text-slate-400">KST</span>
          </span>
          {cal && (
            <span className="flex items-center gap-1.5 text-slate-500" title={cal.rule}>
              <CalendarOff size={13} className="text-brand-500" />
              다음 의무휴업 <b className="text-slate-700">{cal.next_closure.label}</b>
              <span className="rounded-md bg-brand-50 px-1.5 py-0.5 text-[10px] font-bold text-brand-600">
                D-{cal.next_closure.days_left}
              </span>
            </span>
          )}
          {approved.size > 0 && (
            <span className="ml-auto flex items-center gap-1.5 rounded-full bg-emerald-50 px-3 py-1 font-semibold text-emerald-700">
              <Check size={12} strokeWidth={3} /> 오늘 {approved.size}건 처리 · 폐기위험 {cutRate}% 감소
            </span>
          )}
        </div>
      )}

      {closingMode ? (
        <div className="overflow-hidden rounded-2xl bg-slate-900 text-white">
          <div className="flex flex-wrap items-center gap-x-6 gap-y-4 px-5 py-4">
            <div className="flex items-center gap-2.5">
              <MoonStar size={18} className="text-cjorange-400" />
              <div>
                <p className="text-sm font-bold">마감 모드</p>
                <p className="text-[11px] text-slate-400">잔여 재고 집중 처리</p>
              </div>
            </div>

            <div className="flex items-center gap-2">
              <Timer size={15} className="text-slate-400" />
              <div>
                <p className="text-[11px] text-slate-400">마감까지</p>
                <p className="font-mono text-xl font-bold tracking-tight">
                  {String(Math.floor(remain / 60)).padStart(2, "0")}:{String(remain % 60).padStart(2, "0")}
                </p>
              </div>
              <button onClick={() => setDemo(!demo)} title={demo ? "실시간으로 되돌리기" : "시연용 가속 (1초 = 1분)"}
                      className={`rounded-lg px-2 py-1 text-[10px] font-bold transition-colors ${
                        demo ? "bg-cjorange-500 text-white" : "text-slate-500 hover:bg-slate-800 hover:text-slate-300"
                      }`}>
                {demo ? "가속 ×60" : "실시간"}
              </button>
            </div>

            <div className="hidden sm:block">
              <p className="text-[11px] text-slate-400">현재 매장시간 (KST)</p>
              <p className="font-mono text-sm font-semibold">
                {hh}:{mm}
                {!demo && <span className="ml-0.5 text-slate-500">:{String(sec).padStart(2, "0")}</span>}
              </p>
            </div>

            <div>
              <p className="text-[11px] text-slate-400">할인 자동 상향</p>
              <p className="text-sm font-semibold">
                <span className="text-cjorange-400">+{escalation}%p</span>
                <span className="ml-1.5 text-[11px] font-normal text-slate-500">다음 상향 {nextStepIn}분 후</span>
              </p>
            </div>

            <div className="hidden md:block">
              <p className="text-[11px] text-slate-400">잔여 D-Day</p>
              <p className="text-sm font-semibold">
                {pending.filter((i) => i.days_until_expiry === 0).length}건 ·{" "}
                {pending.filter((i) => i.days_until_expiry === 0).reduce((a, i) => a + i.stock_quantity, 0)}개
              </p>
            </div>

            <div className="ml-auto flex gap-2">
              <button onClick={() => setFilter("d0")}
                      className="rounded-xl border border-slate-700 px-3.5 py-2 text-xs font-bold text-slate-300 transition-colors hover:bg-slate-800">
                D-Day만 보기
              </button>
              <button onClick={applyClosingAll} disabled={sending}
                      className="flex items-center gap-1.5 rounded-xl bg-cjorange-500 px-4 py-2 text-xs font-bold text-white transition-transform active:scale-95 disabled:opacity-50">
                <Zap size={13} /> D-Day 전량 상한 적용
              </button>
            </div>
          </div>

          <div className="h-1 bg-slate-800">
            <div className="h-full bg-cjorange-500 transition-all duration-1000"
                 style={{ width: `${Math.min(((240 - remain) / 240) * 100, 100)}%` }} />
          </div>
        </div>
      ) : (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-slate-200 bg-white px-5 py-3">
          <p className="flex items-center gap-2 text-xs text-slate-500">
            <span className="flex items-center gap-1.5 rounded-md bg-emerald-50 px-2 py-0.5 font-semibold text-emerald-700">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" /> 실시간
            </span>
            매장시간 <b className="font-mono font-semibold text-slate-700">{hh}:{mm}:{String(sec).padStart(2, "0")}</b>
            <span className="text-slate-400">KST</span>
            · 마감({Math.floor(CLOSE_MIN / 60)}시) 4시간 전부터 마감 모드로 전환됩니다
          </p>
          <div className="flex gap-2">
            <button onClick={() => setDemo(!demo)}
                    className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors ${
                      demo ? "bg-cjorange-500 text-white" : "text-slate-500 hover:bg-slate-100"
                    }`}>
              {demo ? "가속 중 ×60" : "시연 가속"}
            </button>
            <button onClick={() => setManualClosing(true)}
                    className="rounded-lg px-3 py-1.5 text-xs font-semibold text-slate-500 transition-colors hover:bg-slate-100">
              마감 모드 미리 보기
            </button>
          </div>
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi loading={loading} index={0} label="승인 대기" value={pending.length} unit="건" icon={Tag}
             sub={`D-Day ${pending.filter((i) => i.days_until_expiry === 0).length} · D-1 ${pending.filter((i) => i.days_until_expiry === 1).length} · D-2 ${pending.filter((i) => i.days_until_expiry === 2).length}`} />
        <Kpi loading={loading} index={1} tone="danger" label="오늘 폐기 위험" value={man(kpi.risk)} unit="만원" icon={AlertTriangle}
             sub={kpi.byCat.length ? `${kpi.byCat[0].name} 최대 · 미조치 기준` : "전량 조치 완료"} />
        <Kpi loading={loading} index={2} tone="ok" label="예상 매출" value={man(kpi.revenue)} unit="만원" icon={Wallet}
             sub={approved.size ? `승인 ${approved.size}건에서 발생` : "승인 시 집계됩니다"} />
        <Kpi loading={loading} index={3} label="예상 폐기손실" value={man(kpi.residual)} unit="만원" icon={Trash2}
             sub={`미조치 대비 ${kpi.baseRisk ? Math.round((1 - kpi.residual / kpi.baseRisk) * 100) : 0}% 감소`} />
      </div>

      <div className="grid gap-4 lg:grid-cols-5">
        {/* 오늘의 손실 흐름 — KPI 4종과 정확히 연결되는 워터폴 */}
        <Panel className="lg:col-span-2" title="오늘의 손실 흐름"
               right={<span className="text-[11px] text-slate-400">승인할수록 줄어듭니다</span>}>
          <div className="h-56">
            {loading ? <Skeleton className="h-full w-full" /> : (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={waterfall} margin={{ top: 10, right: 6, left: -20, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" strokeOpacity={0.5} vertical={false} />
                  <XAxis dataKey="name" tickLine={false} axisLine={false} tick={{ fontSize: 11, fill: "#8b95a5" }} interval={0} />
                  <YAxis tickLine={false} axisLine={false} tick={{ fontSize: 11, fill: "#8b95a5" }} tickFormatter={(v) => `${v}만`} />
                  <Tooltip contentStyle={tip} cursor={{ fill: "#f8fafc" }}
                           formatter={(v, n) => (n === "val" ? [`${v}만원`, "금액"] : null)} />
                  <Bar dataKey="base" stackId="a" fill="transparent" />
                  <Bar dataKey="val" stackId="a" radius={[6, 6, 0, 0]} barSize={54}>
                    {waterfall.map((w, i2) => <Cell key={i2} fill={w.color} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>
          <div className="mt-2 space-y-1 text-[11px] text-slate-500">
            <p className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-brand-600" /> 조치하지 않으면 오늘 잃는 금액</p>
            <p className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-emerald-500" /> 추천대로 승인 시 회수되는 손실</p>
            <p className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-slate-300" /> 승인해도 남는 잔여 손실</p>
          </div>
        </Panel>

        {/* 마감까지 소진 예측 — 지금 조치의 효과를 시간축으로 */}
        <Panel className="lg:col-span-3" title="마감까지 소진 예측"
               right={<span className="rounded-md bg-cjblue-50 px-2 py-0.5 text-[11px] font-semibold text-cjblue-700">AI 예측</span>}>
          <div className="h-56">
            {loading ? <Skeleton className="h-full w-full" /> : (
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={sellCurve} margin={{ top: 10, right: 8, left: -20, bottom: 0 }}>
                  <defs>
                    <linearGradient id="gGap" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#059669" stopOpacity={0.22} />
                      <stop offset="100%" stopColor="#059669" stopOpacity={0.02} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" strokeOpacity={0.5} vertical={false} />
                  <XAxis dataKey="label" tickLine={false} axisLine={false} tick={{ fontSize: 11, fill: "#8b95a5" }} />
                  <YAxis tickLine={false} axisLine={false} tick={{ fontSize: 11, fill: "#8b95a5" }} tickFormatter={(v) => `${v}개`} />
                  <Tooltip contentStyle={tip} formatter={(v, n) => [`${v}개`, n]} />
                  <Legend iconType="circle" wrapperStyle={{ fontSize: 11 }} />
                  <ReferenceArea x1={`${closingHour}시`} x2="22시" fill="#0f172a" fillOpacity={0.04} />
                  <Area type="monotone" dataKey="추가판매" stroke="none" fill="url(#gGap)" stackId="gap" legendType="none" tooltipType="none" />
                  <Line type="monotone" dataKey="할인 미적용" stroke="#cbd5e1" strokeWidth={2.2} strokeDasharray="5 4" dot={false} />
                  <Line type="monotone" dataKey="추천 적용" stroke="#059669" strokeWidth={2.6} dot={false} activeDot={{ r: 5 }} />
                  <ReferenceLine x={nowLabel} stroke="#E4002B" strokeWidth={1.6}
                                 label={{ value: "현재", position: "top", fontSize: 11, fill: "#E4002B" }} />
                </ComposedChart>
              </ResponsiveContainer>
            )}
          </div>
          <p className="mt-2 text-[11px] leading-relaxed text-slate-500">
            지금 승인하면 마감({closingHour}시)까지 <b className="text-emerald-600">{extraSold}개</b>를 더 팔 수 있습니다.
            늦어질수록 회수 가능한 물량이 줄어듭니다.
          </p>
        </Panel>
      </div>

      {pendingMgr.size > 0 && (
        <div className="overflow-hidden rounded-2xl border border-brand-200 bg-white">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-brand-100 bg-brand-50 px-5 py-3">
            <div className="flex items-center gap-2">
              <ShieldCheck size={15} className="text-brand-600" />
              <p className="text-sm font-bold text-brand-700">점장 최종 승인 대기 {pendingMgr.size}건</p>
              <span className="rounded-md bg-white px-2 py-0.5 text-[11px] font-semibold text-brand-600">
                {APPROVAL_THRESHOLD}% 초과 할인
              </span>
            </div>
            {canApprove ? (
              <div className="flex gap-2">
                <button onClick={() => onMgrDecision([...pendingMgr.keys()], false)}
                        className="rounded-xl border border-slate-200 bg-white px-3.5 py-2 text-xs font-semibold text-slate-600 hover:bg-slate-50">
                  전체 반려
                </button>
                <button onClick={() => { onMgrDecision([...pendingMgr.keys()], true); onToast({ title: `${pendingMgr.size}건 최종 승인`, desc: "ESL 전송 요청됨" }); }}
                        className="rounded-xl bg-brand-600 px-4 py-2 text-xs font-bold text-white active:scale-95">
                  전체 승인
                </button>
              </div>
            ) : (
              <span className="text-[11px] font-medium text-slate-500">점장 계정으로 로그인해야 승인할 수 있습니다</span>
            )}
          </div>
          {[...pendingMgr.values()].map((i) => (
            <div key={i.product_id} className="flex flex-wrap items-center gap-3 border-b border-slate-100 px-5 py-3 last:border-0">
              <UserCheck size={14} className="shrink-0 text-slate-400" />
              <span className="w-44 shrink-0 truncate text-sm font-semibold">{i.product_name}</span>
              <span className="rounded-md bg-brand-50 px-2 py-0.5 text-xs font-bold text-brand-600">−{i.rate}%</span>
              <span className="min-w-0 flex-1 text-xs text-slate-500">
                {i.requested_by} 요청 · 재고 {i.stock_quantity}개 · 미판매 시 손실 {man(i.expected_loss)}만원
              </span>
              {canApprove && (
                <span className="flex gap-1.5">
                  <button onClick={() => onMgrDecision([i.product_id], false)}
                          className="rounded-lg border border-slate-200 p-1.5 text-slate-400 hover:bg-slate-50" title="반려">
                    <X size={13} />
                  </button>
                  <button onClick={() => { onMgrDecision([i.product_id], true); onToast({ title: "최종 승인", desc: i.product_name }); }}
                          className="rounded-lg bg-brand-600 p-1.5 text-white active:scale-95" title="승인">
                    <Check size={13} strokeWidth={3} />
                  </button>
                </span>
              )}
            </div>
          ))}
        </div>
      )}

      <div>
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <h2 className="flex items-center gap-2 text-base font-bold tracking-tight">
            AI 할인 추천 · 승인 대기열
            {closingMode && (
              <span className="flex items-center gap-1 rounded-md bg-slate-900 px-2 py-0.5 text-[11px] font-semibold text-white">
                <ArrowDownWideNarrow size={11} /> 마감 우선순위 정렬
              </span>
            )}
            {cal?.next_closure.days_left <= 1 && (
              <span className="flex items-center gap-1 rounded-md bg-brand-50 px-2 py-0.5 text-[11px] font-semibold text-brand-600">
                <CalendarOff size={11} /> 휴업 전일 · D+1 상품 포함
              </span>
            )}
          </h2>
          <div className="flex flex-wrap gap-1.5">
            {FILTERS.map((f) => {
              const n = f.key === "all" ? pending.length
                : f.key.startsWith("d") ? pending.filter((i) => i.days_until_expiry === +f.key[1]).length
                : pending.filter((i) => i.category === f.key).length;
              if (n === 0 && f.key !== "all") return null;
              return (
                <button key={f.key} onClick={() => setFilter(f.key)}
                        className={`rounded-full px-3 py-1.5 text-xs font-semibold transition-all ${
                          filter === f.key ? "bg-slate-900 text-white shadow-sm" : "border border-slate-200 bg-white text-slate-600 hover:border-slate-300"
                        }`}>
                  {f.label} {n}
                </button>
              );
            })}
          </div>
        </div>

        <Panel padded={false}>
          {loading ? (
            <div className="space-y-4 p-5">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-16 w-full" />)}</div>
          ) : pending.length === 0 ? (
            <Empty icon={PartyPopper} title="모든 폐기위험 상품 처리 완료"
                   desc={`오늘 ${approved.size}건 승인 · 폐기위험 ${cutRate}% 감소 · 새 위험 상품이 탐지되면 표시됩니다.`} />
          ) : shown.length === 0 ? (
            <Empty icon={Tag} title="해당 조건의 추천이 없습니다" desc="다른 필터를 선택해보세요." />
          ) : (
            shown.map((i) => (
              <Row key={i.product_id} item={i} selected={selected.has(i.product_id)}
                   onToggle={() => toggle(i.product_id)} rate={rateOf(i)}
                   onRate={(v) => setRates({ ...rates, [i.product_id]: v })}
                   onOpen={() => setDetail(i)} />
            ))
          )}
        </Panel>

        {!loading && pending.length > 0 && (
          <div className="sticky bottom-4 mt-4 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-slate-200 bg-white/95 px-5 py-4 shadow-lg backdrop-blur">
            <p className="text-sm text-slate-600">
              {pending.length}건 중 <b className="text-slate-900">{selected.size}건</b> 선택 · 예상 매출{" "}
              <b className="text-emerald-600">
                {man(pending.filter((i) => selected.has(i.product_id))
                  .reduce((sum, i) => sum + i.stock_quantity * i.sell_probability * discounted(i.regular_price, rateOf(i) / 100), 0))}만원
              </b>
            </p>
            <div className="flex gap-2">
              <Button onClick={() => setSel(new Set())}>전체 해제</Button>
              <Button variant="primary" onClick={submit} disabled={selected.size === 0 || sending}>
                {sending && <Loader2 size={15} className="animate-spin" />}
                {sending ? "전송 중" : "선택 승인 → ESL 반영"}
              </Button>
            </div>
          </div>
        )}
      </div>

      {/* AI가 추천하지 않은 상품 */}
      <div>
        <button onClick={() => setShowSkipped(!showSkipped)}
                className="flex w-full items-center gap-2 rounded-2xl border border-slate-200 bg-white px-5 py-3.5 text-left transition-colors hover:bg-slate-50">
          <EyeOff size={15} className="shrink-0 text-slate-400" />
          <span className="flex-1 text-sm font-semibold">
            AI가 추천하지 않은 상품 {(skipped.data ?? []).length}건
            <span className="ml-2 text-xs font-normal text-slate-400">왜 조치가 필요 없는지 확인</span>
          </span>
          <ChevronDown size={16} className={`shrink-0 text-slate-400 transition-transform ${showSkipped ? "rotate-180" : ""}`} />
        </button>
        <div className={`grid transition-all duration-300 ${showSkipped ? "mt-2 grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0"}`}>
          <div className="overflow-hidden">
            <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white">
              {(skipped.data ?? []).map((k) => {
                const tone = k.type === "block" ? "bg-cjorange-50 text-cjorange-700" : k.type === "skip" ? "bg-slate-100 text-slate-500" : "bg-emerald-50 text-emerald-700";
                const label = k.type === "block" ? "규칙 차단" : k.type === "skip" ? "효익 낮음" : "조치 불필요";
                return (
                  <div key={k.product_id} className="flex flex-wrap items-center gap-3 border-b border-slate-100 px-5 py-3 last:border-0">
                    <span className="w-40 shrink-0 text-sm font-semibold">{k.product_name}</span>
                    <span className={`shrink-0 rounded-md px-2 py-0.5 text-[11px] font-bold ${tone}`}>{label}</span>
                    <span className="min-w-0 flex-1 text-xs text-slate-500">{k.reason}</span>
                  </div>
                );
              })}
            </div>
            <p className="mt-2 text-[11px] text-slate-400">
              AI가 침묵한 이유도 기록합니다. 추천이 없는 것과 판단하지 못한 것은 다릅니다.
            </p>
          </div>
        </div>
      </div>

      {detail && (
        <DetailModal item={detail} rate={rateOf(detail)}
          onRate={(v) => setRates({ ...rates, [detail.product_id]: v })}
          onClose={() => setDetail(null)}
          onApprove={() => {
            onApprove([{ ...detail, rate: rateOf(detail) }]);
            setDetail(null);
            onToast({ title: "승인 완료", desc: `${detail.product_name} · ESL 반영 요청됨` });
          }} />
      )}
    </div>
  );
}
