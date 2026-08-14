import { useRef, useState, useEffect, useCallback } from "react";
import {
  AlertTriangle, Boxes, BarChart3, Bell, LogOut, Menu, X, ChevronDown, Settings, TabletSmartphone,
  Smartphone, History as HistoryIcon, Building2, Leaf, FlaskConical, SlidersHorizontal,
  Lock, HelpCircle, ArrowRight,
} from "lucide-react";
import Login from "./pages/Login";
import Home from "./pages/Home";
import Inventory from "./pages/Inventory";
import History from "./pages/History";
import Hq from "./pages/Hq";
import Esg from "./pages/Esg";
import AbTest from "./pages/AbTest";
import PolicySim from "./pages/PolicySim";
import Performance from "./pages/Performance";
import EslModal from "./components/EslModal";
import PdaModal from "./components/PdaModal";
import SettingsModal from "./components/SettingsModal";
import RejectModal from "./components/RejectModal";
import { Toast, BrandMark } from "./components/ui";
import { BRAND } from "./lib/brand";
import {
  getNotifications, ROLES, loadPolicy,
  requestReprice, closeRepriceFlow, requestManagerApproval, approveReprice, getRepricePending, REJECT_REASONS,
} from "./lib/api";

const NAV = [
  { key: "home", label: "폐기위험 대응", icon: AlertTriangle, desc: "AI 추천 검토·승인", group: "점포" },
  { key: "inv", label: "재고 모니터링", icon: Boxes, desc: "전체 신선 재고", group: "점포" },
  { key: "hist", label: "승인 이력", icon: HistoryIcon, desc: "가격 변경 기록·조정 패턴", group: "점포" },
  { key: "perf", label: "성과 리포트", icon: BarChart3, desc: "도입 효과", group: "점포" },
  { key: "hq", label: "본사 대시보드", icon: Building2, desc: "전 점포 비교·확산 현황", group: "본사" },
  { key: "esg", label: "ESG 리포트", icon: Leaf, desc: "폐기 감축의 탄소 환산", group: "본사" },
  { key: "ab", label: "효과 검증", icon: FlaskConical, desc: "적용·대조 점포 비교 실험", group: "본사" },
  { key: "sim", label: "정책 시뮬레이터", icon: SlidersHorizontal, desc: "할인 정책 변경 영향 분석", group: "본사" },
];

const policyItemKey = (item) => `${item.product_id}:${item.dte_index}`;

export default function App() {
  const [auth, setAuth] = useState(null);
  const [tab, setTab] = useState("home");
  const [storeId, setStoreId] = useState("S01");
  /* 할인 정책 — 점포별로 저장/로드됩니다. 승인 로직은 이 값(특히 two_step_over)을 기준으로 동작합니다. */
  const [policy, setPolicy] = useState(() => loadPolicy("S01"));
  const [openMenu, setOpenMenu] = useState(false);
  const [storeOpen, setStoreOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const [eslOpen, setEslOpen] = useState(false);
  const [pdaOpen, setPdaOpen] = useState(false);
  const [setOpen, setSetOpen] = useState(false);
  const [noticeOpen, setNoticeOpen] = useState(false);
  const [notices, setNotices] = useState([]);
  const [tourStep, setTourStep] = useState(0);

  /* 대한민국 표준시 실시간 표시 */
  const fmtKst = () =>
    new Date().toLocaleString("ko-KR", {
      timeZone: "Asia/Seoul", month: "long", day: "numeric", weekday: "short",
      hour: "2-digit", minute: "2-digit", hour12: false,
    });
  /* 승인 시각(초 단위) — ESL 카드의 "반영 완료 · HH:MM:SS" 표시용 */
  const nowHms = () =>
    new Date().toLocaleTimeString("ko-KR", { timeZone: "Asia/Seoul", hour12: false });
  const [nowKst, setNowKst] = useState(fmtKst);
  useEffect(() => {
    const t = setInterval(() => setNowKst(fmtKst()), 1000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => { getNotifications().then(setNotices).catch(() => {}); }, []);
  const [toast, setToast] = useState(null);

  /* 승인 상태 — 화면 전체가 이 값을 공유합니다 */
  const [approved, setApproved] = useState(new Map());
  const [rates, setRates] = useState({});
  const [items, setItems] = useState([]);

  /* 2단 결재: 임계값 이하는 담당자 승인으로 확정, 초과는 점장 승인 대기 */
  const [pendingMgr, setPendingMgr] = useState(new Map());

  /* ── 반려 이후의 업무 흐름 ────────────────────────────────────────
     점장 반려는 프로세스의 끝이 아닙니다. 아래 3개 상태로 이어집니다.
       repricing  : 반려 사유를 제약으로 넘겨 AI가 새 할인율을 계산 중
       restaged   : 새 추천안 도착 · 담당자 재검토 대기
       closedFlow : 재추천 한도 소진 → 수동 지정 / 할인 미적용으로 종결
     ───────────────────────────────────────────────────────────── */
  const [repricing, setRepricing] = useState(new Map());
  const [restaged, setRestaged] = useState(new Map());
  const [closedFlow, setClosedFlow] = useState(new Map());
  const [rejectTarget, setRejectTarget] = useState(null);   // { items: [...], round }
  const recommendationRevision = useRef("");

  const handleItemsLoaded = (nextItems, loadedStoreId) => {
    const requestIds = [...new Set(nextItems.map((item) => item.request_id).filter(Boolean))].sort().join("|");
    const nextRevision = `${loadedStoreId}:${requestIds || "EMPTY"}`;
    if (nextItems.length > 0 && recommendationRevision.current && recommendationRevision.current !== nextRevision) {
      setApproved(new Map());
      setPendingMgr(new Map());
      setRates({});
      setRepricing(new Map());
      setRestaged(new Map());
      setClosedFlow(new Map());
    }
    recommendationRevision.current = nextRevision;
    setItems(nextItems);
  };

  const handleApprove = (list) => {
    const direct = list.filter((i) => i.rate <= policy.two_step_over);
    const escalate = list.filter((i) => i.rate > policy.two_step_over);
    if (direct.length) {
      setApproved((prev) => {
        const next = new Map(prev);
        direct.forEach((i) => next.set(policyItemKey(i), {
          ...i,
          approved_rate: i.rate / 100,
          approved_at: nowHms(),
        }));
        return next;
      });
    }
    if (escalate.length) {
      setPendingMgr((prev) => {
        const next = new Map(prev);
        escalate.forEach((i) => next.set(policyItemKey(i), { ...i, requested_by: auth?.user?.name ?? "담당자" }));
        return next;
      });
    }
    return { direct: direct.length, escalate: escalate.length };
  };

  /* 점장 최종 승인 — 반려는 handleMgrReject(사유 입력 후 재추천)로 분리했습니다 */
  const handleMgrDecision = (ids, ok) => {
    if (!ok) return;                       // 반려는 RejectModal 경유
    setPendingMgr((prev) => {
      const next = new Map(prev);
      ids.forEach((id) => {
        const item = next.get(id);
        if (item) {
          setApproved((a) => {
            const m = new Map(a);
            m.set(id, {
              ...item,
              approved_rate: item.rate / 100,
              approved_at: nowHms(),
            });
            return m;
          });
        }
        next.delete(id);
      });
      return next;
    });
  };

  const handleManagerItemsLoaded = useCallback((nextItems, loadedStoreId) => {
    if (loadedStoreId !== storeId) return;
    setPendingMgr(new Map(nextItems.map((item) => [
      policyItemKey(item),
      { ...item, requested_by: item.requested_by ?? "담당자" },
    ])));
  }, [storeId]);

  useEffect(() => {
    if (!auth) return;
    getRepricePending(storeId)
      .then((rows) => setRestaged(new Map(rows.map((item) => [policyItemKey(item), item]))))
      .catch(() => {});
  }, [auth, storeId]);

  const dropFrom = (setter, ids) =>
    setter((prev) => {
      const next = new Map(prev);
      ids.forEach((id) => next.delete(id));
      return next;
    });

  const fire = (t) => {
    setToast(t);
    setTimeout(() => setToast(null), 3200);
  };

  if (!auth)
    return (
      <Login
        onLogin={(res) => {
          setAuth(res);
          setStoreId(res.storeId ?? "S01");
          setPolicy(loadPolicy(res.storeId ?? "S01"));
          let seen = false;
          try { seen = !!localStorage.getItem("fw_tour_seen"); } catch { seen = false; }
          if (!seen) setTimeout(() => setTourStep(1), 400);   // 최초 1회만 자동 안내
        }}
      />
    );

  const changeStore = (id) => {
    setStoreId(id);
    setPolicy(loadPolicy(id));
    setApproved(new Map());
    setPendingMgr(new Map());
    setRepricing(new Map());
    setRestaged(new Map());
    setClosedFlow(new Map());
    setRejectTarget(null);
    setRates({});
    setStoreOpen(false);
  };

  /* ── 반려 분기 ─────────────────────────────────────────────────
     ① 반려 사유 입력 → ② AI 재계산 → ③ 담당자 재검토 대기열 복귀
     ④ 새 할인율이 임계값을 넘으면 다시 점장 결재, 넘지 않으면 담당자 확정
     ⑤ 재추천 한도(2회) 소진 시 수동 지정 / 할인 미적용으로 강제 종결
     ──────────────────────────────────────────────────────────── */
  const openReject = (list, round = 0) => setRejectTarget({ items: list, round });

  const runReprice = async ({ code, memo }) => {
    const list = rejectTarget?.items ?? [];
    const round = (rejectTarget?.round ?? 0) + 1;
    setRejectTarget(null);
    if (!list.length) return;
    const ids = list.map(policyItemKey);

    dropFrom(setPendingMgr, ids);
    dropFrom(setRestaged, ids);
    setRepricing((prev) => {
      const next = new Map(prev);
      list.forEach((i) => next.set(policyItemKey(i), { ...i, reason_code: code, memo, round }));
      return next;
    });
    fire({
      title: `${list.length}건 반려 · AI 재계산 시작`,
      desc: `${REJECT_REASONS.find((r) => r.code === code)?.label ?? "기타"} 제약을 반영해 새 할인율을 계산합니다`,
    });

    try {
      const res = await requestReprice(
        storeId,
        list.map((i) => ({ item: i, previous_rate: i.rate, reason_code: code, memo, round }))
      );
      const byId = new Map(res.map((r) => [policyItemKey(r), r]));
      setRestaged((prev) => {
        const next = new Map(prev);
        list.forEach((i) => {
          const key = policyItemKey(i);
          const r = byId.get(key);
          if (r) next.set(key, { ...i, round, reprice: r });
        });
        return next;
      });
      fire({ title: `${res.length}건 재추천 완료`, desc: "담당자 재검토 대기열로 이동했습니다" });
    } catch (e) {
      /* 실패 시 결재 대기 상태로 되돌립니다 — 건이 증발하지 않게 */
      setPendingMgr((prev) => {
        const next = new Map(prev);
        list.forEach((i) => next.set(policyItemKey(i), i));
        return next;
      });
      fire({ tone: "error", title: "재추천 실패", desc: e.message });
    } finally {
      dropFrom(setRepricing, ids);
    }
  };

  /* 재추천 한도 소진 → 강제 종결 (manual: 점장 수동 지정 · no_discount: 할인 미적용) */
  const forceClose = async (mode, targets) => {
    const list = targets ?? rejectTarget?.items ?? [];
    setRejectTarget(null);
    if (!list.length) return;
    const ids = list.map(policyItemKey);
    dropFrom(setPendingMgr, ids);
    dropFrom(setRestaged, ids);
    setClosedFlow((prev) => {
      const next = new Map(prev);
      list.forEach((i) =>
        next.set(policyItemKey(i), {
          ...i, mode,
          rate: mode === "manual" ? Math.max(0, (i.rate ?? 0) - 5) : 0,
          cap: i.policy_cap ?? policy.max_discount,
        })
      );
      return next;
    });
    try { await closeRepriceFlow(storeId, { mode, item_keys: ids }); } catch { /* 기록 실패해도 화면 상태는 유지 */ }
    fire(mode === "manual"
      ? { title: `${list.length}건 수동 가격 지정으로 전환`, desc: "점장이 직접 할인율을 입력해 확정합니다" }
      : { title: `${list.length}건 할인 미적용 종결`, desc: "정가 유지 · 미판매분 폐기 처리" });
  };

  /* 담당자 재검토 승인 — 새 할인율이 임계값을 넘으면 다시 점장 결재로 */
  const acceptRestaged = async (id) => {
    const item = restaged.get(id);
    if (!item) return;
    const rate = item.reprice.new_rate;
    const approvalItem = {
      request_id: item.request_id,
      product_id: item.product_id,
      dte_index: item.dte_index,
      approved_rate: rate / 100,
    };
    try {
      if (rate > policy.two_step_over) {
        await requestManagerApproval(storeId, [approvalItem]);
        setPendingMgr((prev) => {
          const next = new Map(prev);
          next.set(id, { ...item, rate, round: item.round, requested_by: auth?.user?.name ?? "담당자" });
          return next;
        });
        fire({ title: "점장 재결재 요청", desc: `${item.product_name} · ${rate}% (${policy.two_step_over}% 초과)` });
      } else {
        await approveReprice(storeId, [approvalItem]);
        setApproved((prev) => {
          const next = new Map(prev);
          next.set(id, { rate, name: item.product_name, esl: item.esl_applicable, regular_price: item.regular_price, approved_at: nowHms() });
          return next;
        });
        fire({ title: "재추천 승인 완료", desc: `${item.product_name} · ${rate}% RDS 반영 완료` });
      }
      dropFrom(setRestaged, [id]);
    } catch (error) {
      fire({ title: "재추천 승인 실패", desc: error.message });
    }
  };

  /* 수동 지정 확정 → 승인 상태로 편입(ESL 반영 대상) */
  const finalizeManual = (id, rate) => {
    const item = closedFlow.get(id);
    if (!item) return;
    dropFrom(setClosedFlow, [id]);
    setApproved((prev) => {
      const next = new Map(prev);
      next.set(id, { rate, name: item.product_name, esl: item.esl_applicable, regular_price: item.regular_price, approved_at: nowHms() });
      return next;
    });
    fire({ title: "수동 가격 확정", desc: `${item.product_name} · ${rate}% ESL 반영 요청됨` });
  };

  const role = ROLES[auth.role] ?? ROLES.manager;
  const allowed = (k) => role.scope.includes(k);
  const store = auth.stores.find((s) => s.store_id === storeId) ?? auth.stores[0];
  /* 대기 배지 — 반려 후속 처리 중인 건도 대기열에서 빠집니다 */
  const inFlow = new Set([
    ...approved.keys(), ...pendingMgr.keys(),
    ...repricing.keys(), ...restaged.keys(), ...closedFlow.keys(),
  ]);
  const pendingCount = Math.max(items.length - inFlow.size, 0);
  const current = NAV.find((n) => n.key === tab);

  const NavList = () => (
    <nav className="flex-1 space-y-1 px-3">
      {["점포", "본사"].map((g) => (
        <div key={g} className={g === "본사" ? "mt-4 border-t border-slate-800 pt-4" : ""}>
          <p className="px-3 pb-1.5 text-[10px] font-bold uppercase tracking-wider text-slate-600">{g}</p>
          {NAV.filter((n) => n.group === g).map(({ key, label, icon: Icon }) => (
            <button
              key={key}
              disabled={!allowed(key)}
              title={allowed(key) ? "" : "본사 운영팀 권한이 필요합니다"}
              onClick={() => { if (allowed(key)) { setTab(key); setOpenMenu(false); } }}
              className={`flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-sm transition-all ${
                tab === key ? "bg-slate-800 font-semibold text-white"
                : allowed(key) ? "text-slate-400 hover:bg-slate-800/60 hover:text-slate-200"
                : "cursor-not-allowed text-slate-600"
              }`}
            >
              <Icon size={17} />
              <span className="flex-1 text-left">{label}</span>
              {key === "home" && pendingCount > 0 && (
                <span className="rounded-full bg-brand-600 px-2 py-0.5 text-[11px] font-bold text-white">{pendingCount}</span>
              )}
              {!allowed(key) && <Lock size={12} className="text-slate-600" />}
            </button>
          ))}
        </div>
      ))}
    </nav>
  );

  return (
    <div className="flex min-h-screen">
      {/* 사이드바 */}
      <aside className="hidden w-56 shrink-0 flex-col bg-slate-900 py-6 lg:flex">
        <div className="px-6 pb-8">
          <div className="flex items-center gap-2.5">
            <BrandMark size={26} plate />
            <p className="text-lg font-bold tracking-tight text-white">
              신<span className="text-brand-500">선</span>
            </p>
          </div>
          <p className="mt-1 text-[11px] text-slate-500">{store.name} · 신선1부문</p>
        </div>
        <NavList />
        <div className="mt-auto px-3">
          <div className="px-3 pt-4">
            <p className="text-[11px] leading-relaxed text-slate-500">
              <span className="text-slate-400">{BRAND.vendorRole}</span> {BRAND.vendor}
            </p>
            <p className="mt-1 text-[11px] leading-relaxed text-slate-600">{BRAND.project} · {BRAND.version}</p>
          </div>
        </div>
      </aside>

      {/* 모바일 드로어 */}
      {openMenu && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-slate-900/50" onClick={() => setOpenMenu(false)} />
          <div className="absolute left-0 top-0 flex h-full w-64 flex-col bg-slate-900 py-6">
            <div className="flex items-center justify-between px-6 pb-4">
              <span className="flex items-center gap-2 text-lg font-bold text-white">
                <BrandMark size={22} plate />신<span className="text-brand-500">선</span>
              </span>
              <button onClick={() => setOpenMenu(false)} className="text-slate-400"><X size={20} /></button>
            </div>
            <NavList />
            <button onClick={() => { setEslOpen(true); setOpenMenu(false); }}
                    className="mx-3 flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm text-slate-400">
              <TabletSmartphone size={16} /> ESL 현황
            </button>
            <button onClick={() => { setPdaOpen(true); setOpenMenu(false); }}
                    className="mx-3 flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm text-slate-400">
              <Smartphone size={16} /> 현장 PDA 모드
            </button>
          </div>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex items-center justify-between gap-3 border-b border-slate-200 bg-white/90 px-5 py-4 backdrop-blur lg:px-8">
          <div className="flex min-w-0 items-center gap-3">
            <button onClick={() => setOpenMenu(true)} className="rounded-lg p-1.5 text-slate-500 hover:bg-slate-100 lg:hidden">
              <Menu size={20} />
            </button>
            <div className="min-w-0">
              <h1 className="truncate text-lg font-bold tracking-tight lg:text-xl">{current.label}</h1>
              <p className="mt-0.5 truncate text-xs text-slate-400">
                {current.desc} · {store.name} · <span className="font-mono">{nowKst}</span> KST
              </p>
            </div>
          </div>

          <div className="flex shrink-0 items-center gap-2">
            {/* 매장 선택 */}
            <div className="relative">
              <button onClick={() => setStoreOpen(!storeOpen)}
                      className="flex items-center gap-1.5 rounded-xl border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-700 transition-colors hover:bg-slate-50">
                <span className="hidden sm:inline">{store.name}</span>
                <span className="sm:hidden">{store.store_id}</span>
                <ChevronDown size={13} className={`transition-transform ${storeOpen ? "rotate-180" : ""}`} />
              </button>
              {storeOpen && (
                <>
                  <div className="fixed inset-0 z-10" onClick={() => setStoreOpen(false)} />
                  <div className="absolute right-0 z-20 mt-1.5 w-52 overflow-hidden rounded-xl border border-slate-200 bg-white py-1 shadow-lg">
                    {auth.stores.map((s) => (
                      <button key={s.store_id} onClick={() => changeStore(s.store_id)}
                              className={`flex w-full items-center justify-between px-3 py-2 text-xs transition-colors hover:bg-slate-50 ${
                                s.store_id === storeId ? "font-semibold text-brand-600" : "text-slate-600"
                              }`}>
                        <span>{s.name}</span>
                        {s.store_id === storeId && <span className="h-1.5 w-1.5 rounded-full bg-brand-600" />}
                      </button>
                    ))}
                  </div>
                </>
              )}
            </div>

            {/* ESL 상태 → 팝업 */}
            <button onClick={() => setEslOpen(true)} title="ESL 전송 현황"
                    className="flex items-center gap-1.5 rounded-full bg-cjorange-50 px-2.5 py-1.5 text-xs font-semibold text-cjorange-600 transition-colors hover:bg-cjorange-100 sm:px-3">
              <TabletSmartphone size={14} />
              <span className="hidden sm:inline">
                ESL {approved.size > 0 ? `${approved.size}건 전송됨` : "2건 조치 필요"}
              </span>
              <span className="sm:hidden">{approved.size > 0 ? approved.size : 2}</span>
            </button>

            <button onClick={() => setTourStep(1)} title="사용법 안내"
                    className="hidden rounded-lg p-2 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600 sm:block">
              <HelpCircle size={18} />
            </button>

            <button onClick={() => setPdaOpen(true)} title="현장 PDA 모드"
                    className="rounded-lg p-2 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600">
              <Smartphone size={18} />
            </button>

            <div className="relative">
              <button onClick={() => setNoticeOpen(!noticeOpen)}
                      className="relative rounded-lg p-2 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600">
                <Bell size={18} />
                {notices.length > 0 && <span className="absolute right-1.5 top-1.5 h-2 w-2 rounded-full bg-brand-500" />}
              </button>
              {noticeOpen && (
                <>
                  <div className="fixed inset-0 z-10" onClick={() => setNoticeOpen(false)} />
                  <div className="absolute right-0 z-20 mt-1.5 w-80 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-xl">
                    <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
                      <p className="text-sm font-bold">알림</p>
                      <span className="text-[11px] text-slate-400">{notices.length}건</span>
                    </div>
                    <div className="max-h-80 overflow-y-auto">
                      {notices.map((n) => {
                        const dot = n.type === "danger" ? "bg-brand-500" : n.type === "warning" ? "bg-cjorange-500" : "bg-cjblue-500";
                        return (
                          <div key={n.id} className="flex gap-2.5 border-b border-slate-50 px-4 py-3 last:border-0 hover:bg-slate-50">
                            <span className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${dot}`} />
                            <div className="min-w-0 flex-1">
                              <p className="text-xs font-semibold">{n.title}</p>
                              <p className="mt-0.5 text-[11px] leading-relaxed text-slate-500">{n.desc}</p>
                            </div>
                            <span className="shrink-0 text-[10px] text-slate-400">{n.time}</span>
                          </div>
                        );
                      })}
                    </div>
                    <button onClick={() => { setNotices([]); setNoticeOpen(false); }}
                            className="w-full border-t border-slate-100 py-2.5 text-xs font-semibold text-slate-500 hover:bg-slate-50">
                      모두 읽음 처리
                    </button>
                  </div>
                </>
              )}
            </div>

            {/* 프로필 드롭다운 */}
            <div className="relative">
              <button onClick={() => setProfileOpen(!profileOpen)}
                      className="flex h-9 w-9 items-center justify-center rounded-full bg-slate-100 text-sm font-semibold text-slate-600 transition-colors hover:bg-slate-200">
                {auth.user.name[0]}
              </button>
              {profileOpen && (
                <>
                  <div className="fixed inset-0 z-10" onClick={() => setProfileOpen(false)} />
                  <div className="absolute right-0 z-20 mt-1.5 w-52 overflow-hidden rounded-xl border border-slate-200 bg-white py-1 shadow-lg">
                    <div className="border-b border-slate-100 px-3 py-2.5">
                      <p className="text-sm font-semibold">{auth.user.name}</p>
                      <p className="text-xs text-slate-400">{role.label}</p>
                    </div>
                    <button onClick={() => { if (role.canPolicy) { setSetOpen(true); setProfileOpen(false); } }}
                            disabled={!role.canPolicy}
                            title={role.canPolicy ? "" : "점장 이상 권한이 필요합니다"}
                            className={`flex w-full items-center gap-2 px-3 py-2 text-xs ${
                              role.canPolicy ? "text-slate-600 hover:bg-slate-50" : "cursor-not-allowed text-slate-300"
                            }`}>
                      <Settings size={13} /> 할인 정책 설정
                      {!role.canPolicy && <Lock size={11} className="ml-auto" />}
                    </button>
                    <button onClick={() => setAuth(null)} className="flex w-full items-center gap-2 px-3 py-2 text-xs text-slate-600 hover:bg-slate-50">
                      <LogOut size={13} /> 로그아웃
                    </button>
                  </div>
                </>
              )}
            </div>
          </div>
        </header>

        <main className="flex-1 p-5 lg:p-8">
          {tab === "home" && (
            <Home storeId={storeId} onToast={fire} approved={approved} onApprove={handleApprove}
                  rates={rates} setRates={setRates} onItemsLoaded={handleItemsLoaded}
                  role={role} pendingMgr={pendingMgr} onMgrDecision={handleMgrDecision}
                  onManagerItemsLoaded={handleManagerItemsLoaded}
                  repricing={repricing} restaged={restaged} closedFlow={closedFlow}
                  onOpenReject={openReject} onAcceptRestaged={acceptRestaged}
                  onFinalizeManual={finalizeManual}
                  onDiscard={(id) => forceClose("no_discount", [restaged.get(id)].filter(Boolean))}
                  policy={policy} threshold={policy.two_step_over} />
          )}
          {tab === "hist" && <History storeId={storeId} onToast={fire} />}
          {tab === "hq" && <Hq onPickStore={(id) => { changeStore(id); setTab("home"); }} />}
          {tab === "esg" && <Esg scope="hq" />}
          {tab === "ab" && <AbTest />}
          {tab === "sim" && <PolicySim onToast={fire} />}
          {tab === "inv" && <Inventory storeId={storeId} onToast={fire} policy={policy} />}
          {tab === "perf" && <Performance storeId={storeId} approvedCount={approved.size} />}
        </main>

        <footer className="border-t border-slate-200 px-5 py-4 text-[11px] leading-relaxed text-slate-400 lg:px-8">
          본 화면은 발표·시연용 <b className="font-semibold text-slate-500">프로토타입</b>입니다. 표시된 수치는 공개 판매데이터(M5·Favorita)와
          합성 재고·유통기한 데이터를 가정한 예시값이며 실제 모델 성능을 보장하지 않습니다.
          AI는 순이익 최대화 로직으로 할인율을 <b className="font-semibold text-slate-500">추천만</b> 하며(본사지침 상한 40%),
          최종 반영은 반드시 관리자 승인을 거칩니다. 근거: 다이나믹 프라이싱 폐기 −20.8% · 이익 +2.9% (Sanders 2024, Marketing Science).
          <span className="mt-1 block">목표고객 {BRAND.client}(B2B) · {BRAND.vendorRole} {BRAND.vendor}(가정) · {BRAND.project}</span>
        </footer>
      </div>

      {eslOpen && <EslModal storeId={storeId} approved={approved} onClose={() => setEslOpen(false)} onToast={fire} />}
      {tourStep > 0 && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-slate-900/60 p-6 backdrop-blur-sm">
          <div className="animate-fade-up w-full max-w-md rounded-3xl bg-white p-6 shadow-2xl">
            {[
              { t: "폐기위험 대응부터 시작하세요", d: "AI가 오늘 폐기 위험이 있는 상품과 추천 할인율을 정리해둡니다. 체크박스로 골라 한 번에 승인하면 ESL에 반영됩니다.", i: AlertTriangle },
              { t: "추천 근거를 확인할 수 있습니다", d: "상품의 '손익 시뮬레이션'을 열면 할인율별 기대 손익 곡선이 나옵니다. 왜 그 할인율인지 그래프로 확인하고 직접 조정할 수도 있습니다.", i: FlaskConical },
              { t: "현장에서는 PDA 모드로", d: "상단 휴대폰 아이콘을 누르면 매대에서 스캔해 바로 승인하는 화면이 열립니다. 오프라인에서도 저장됩니다.", i: Smartphone },
            ].map((step, i) => (
              tourStep === i + 1 && (
                <div key={i}>
                  <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-brand-50">
                    <step.i size={20} className="text-brand-600" />
                  </div>
                  <p className="mt-4 text-lg font-bold tracking-tight">{step.t}</p>
                  <p className="mt-2 text-sm leading-relaxed text-slate-500">{step.d}</p>
                  <div className="mt-6 flex items-center justify-between">
                    <div className="flex gap-1.5">
                      {[1, 2, 3].map((n) => (
                        <span key={n} className={`h-1.5 rounded-full transition-all ${n === tourStep ? "w-5 bg-brand-600" : "w-1.5 bg-slate-200"}`} />
                      ))}
                    </div>
                    <div className="flex gap-2">
                      <button onClick={() => { setTourStep(0); try { localStorage.setItem("fw_tour_seen", "1"); } catch { /* noop */ } }}
                              className="rounded-xl px-3 py-2 text-xs font-semibold text-slate-400 hover:text-slate-600">다시 보지 않기</button>
                      <button onClick={() => {
                                if (tourStep >= 3) { setTourStep(0); try { localStorage.setItem("fw_tour_seen", "1"); } catch { /* noop */ } }
                                else setTourStep(tourStep + 1);
                              }}
                              className="flex items-center gap-1.5 rounded-xl bg-brand-600 px-4 py-2 text-xs font-bold text-white active:scale-95">
                        {tourStep >= 3 ? "시작하기" : "다음"} <ArrowRight size={13} />
                      </button>
                    </div>
                  </div>
                </div>
              )
            ))}
          </div>
        </div>
      )}

      {setOpen && (
        <SettingsModal storeId={storeId} policy={policy} onSaved={setPolicy}
                       onClose={() => setSetOpen(false)} onToast={fire} />
      )}
      {pdaOpen && (
        <PdaModal items={items} approvedIds={inFlow} onApprove={handleApprove}
                  threshold={policy.two_step_over} onClose={() => setPdaOpen(false)} onToast={fire} />
      )}
      {rejectTarget && (
        <RejectModal targets={rejectTarget.items} round={rejectTarget.round}
                     onClose={() => setRejectTarget(null)}
                     onSubmit={runReprice}
                     onForceClose={(mode) => forceClose(mode)} />
      )}

      <Toast show={!!toast} tone={toast?.tone} title={toast?.title} desc={toast?.desc} />
    </div>
  );
}
