/* ------------------------------------------------------------------
   API 레이어 — 백엔드 완성 전까지 목(mock)으로 동작합니다.
   USE_MOCK 를 false 로 바꾸면 실제 서버를 호출합니다.
   ------------------------------------------------------------------ */
export const USE_MOCK = import.meta.env.VITE_USE_MOCK !== "false";
const USE_SUMMARY_MOCK = import.meta.env.VITE_USE_SUMMARY_MOCK !== "false";
export const USE_RECOMMENDATIONS_MOCK = import.meta.env.VITE_USE_RECOMMENDATIONS_MOCK !== "false";
const USE_INVENTORY_MOCK = import.meta.env.VITE_USE_INVENTORY_MOCK !== "false";
const BASE = import.meta.env.VITE_API_BASE_URL || "/api";
const delay = (ms) => new Promise((r) => setTimeout(r, ms));
const ACTIVE_STORE_IDS = new Set(["S01", "S02", "S03"]);

const STORES = [
  { store_id: "S01", name: "롯데마트 서울역점", area_type: "complex" },
  { store_id: "S02", name: "롯데마트 양평점", area_type: "residence" },
  { store_id: "S03", name: "롯데마트 잠실점", area_type: "office" },
];

/* 원천 사실만 보관합니다 — 추천 할인율·판매확률·손익은 프라이싱 엔진이 계산합니다.
   (하드코딩된 20/30/40%를 제거해야 다이나믹 프라이싱이 성립합니다) */
const BASE_RECS = [
  { product_id: "P001", product_name: "한우 등심 300g",   category: "축산",   days_until_expiry: 0, stock_quantity: 8,  cost: 38000, regular_price: 52000, turnover: 0.42, esl_applicable: true },
  { product_id: "P014", product_name: "삼겹살 500g",       category: "축산",   days_until_expiry: 1, stock_quantity: 12, cost: 13100, regular_price: 18650, turnover: 0.72, esl_applicable: true },
  { product_id: "P019", product_name: "손질 오징어 2마리", category: "수산",   days_until_expiry: 0, stock_quantity: 9,  cost: 5200,  regular_price: 8900,  turnover: 0.38, esl_applicable: true },
  { product_id: "P036", product_name: "모듬 초밥 12P",     category: "즉석",   days_until_expiry: 0, stock_quantity: 6,  cost: 8400,  regular_price: 13900, turnover: 0.69, esl_applicable: false },
  { product_id: "P008", product_name: "닭가슴살 1kg",      category: "축산",   days_until_expiry: 1, stock_quantity: 15, cost: 9800,  regular_price: 14500, turnover: 0.55, esl_applicable: true },
  { product_id: "P027", product_name: "우유 1L",           category: "유제품", days_until_expiry: 2, stock_quantity: 24, cost: 2100,  regular_price: 3130,  turnover: 0.88, esl_applicable: true },
  { product_id: "P031", product_name: "플레인 요거트 4입", category: "유제품", days_until_expiry: 2, stock_quantity: 18, cost: 2600,  regular_price: 3980,  turnover: 0.74, esl_applicable: true },
  { product_id: "P042", product_name: "손질 대파 300g",    category: "청과",   days_until_expiry: 0, stock_quantity: 22, cost: 1500,  regular_price: 2450,  turnover: 0.81, esl_applicable: true },
  { product_id: "P011", product_name: "국내산 사과 5입",   category: "청과",   days_until_expiry: 2, stock_quantity: 14, cost: 8900,  regular_price: 12400, turnover: 0.66, esl_applicable: true },
  { product_id: "P022", product_name: "모둠 쌈채소",       category: "청과",   days_until_expiry: 1, stock_quantity: 11, cost: 2200,  regular_price: 3500,  turnover: 0.70, esl_applicable: true },
];

const STORE_FACTOR = { S01: 1, S02: 0.86, S03: 0.78 };

/* 잔여일별 할인 상한 — 정책 설정 화면에서 바꾸면 추천값이 실제로 달라집니다 */
export function dayCap(days, policy) {
  const p = policy ?? DEFAULT_POLICY;
  const byDay = { 0: p.step_d0, 1: p.step_d1, 2: p.step_d2 };
  return Math.min(byDay[days] ?? p.step_d2, p.max_discount);
}

function scaledRecs(storeId) {
  const f = STORE_FACTOR[storeId] ?? 1;
  return BASE_RECS.map((r) => ({ ...r, stock_quantity: Math.max(1, Math.round(r.stock_quantity * f)) }));
}

function mockRecs(storeId, policyOverride) {
  const policy = policyOverride ?? loadPolicy(storeId);
  return scaledRecs(storeId)
    .map((r) => withRecommendation(r, dayCap(r.days_until_expiry, policy), policy.max_discount))
    /* 추천 할인율 0% = AI가 "조치 불필요"로 판단한 건 → 승인 대기열에서 제외 */
    .filter((r) => r.recommended_rate > 0);
}

/* ---------- 정책 변경의 실시간 영향 미리보기 ----------
   설정 화면에서 슬라이더를 움직일 때마다 호출됩니다.
   "상한을 낮추면 무슨 일이 벌어지는가"를 저장 전에 보여주는 것이 목적입니다. */
export function previewPolicyImpact(storeId, policy) {
  const all = scaledRecs(storeId);
  const evaluate = (p) => {
    const rows = all.map((r) => withRecommendation(r, dayCap(r.days_until_expiry, p), p.max_discount));
    const active = rows.filter((r) => r.recommended_rate > 0);
    const rates = active.map((r) => Math.round(r.recommended_rate * 100));
    return {
      total: rows.length,
      pending: active.length,
      dropped: rows.length - active.length,
      capped: active.filter((r) => r.capped_by_policy).length,
      minRate: rates.length ? Math.min(...rates) : 0,
      maxRate: rates.length ? Math.max(...rates) : 0,
      escalate: active.filter((r) => Math.round(r.recommended_rate * 100) > p.two_step_over).length,
      /* 미조치(전건 0%) 대비 순이익 개선 합계 */
      gain: active.reduce((s, r) => s + (r.expected_gain ?? 0), 0),
      /* 방치 시 잃는 금액 중 조치되지 않고 남는 부분 */
      unaddressed: rows.filter((r) => r.recommended_rate === 0).reduce((s, r) => s + r.expected_loss, 0),
    };
  };
  const now = evaluate(policy);
  const base = evaluate(DEFAULT_POLICY);
  /* 결재 임계값이 D-Day 상한 이상이면 2단 결재가 구조적으로 발생할 수 없습니다 */
  const maxReachable = Math.max(dayCap(0, policy), dayCap(1, policy), dayCap(2, policy));
  return {
    ...now,
    gainDelta: now.gain - base.gain,
    baseGain: base.gain,
    basePending: base.pending,
    approvalMoot: policy.two_step_over >= maxReachable,
    maxReachable,
  };
}

function mockSummary(storeId) {
  const recs = mockRecs(storeId);
  const risk = recs.reduce((s, r) => s + r.expected_loss, 0);
  let revenue = 0, residual = 0;
  recs.forEach((r) => {
    const sold = r.stock_quantity * r.sell_probability;
    const price = Math.round((r.regular_price * (1 - r.recommended_rate)) / 10) * 10;
    revenue += sold * price;
    residual += (r.stock_quantity - sold) * r.cost;
  });
  const byCat = Object.entries(
    recs.reduce((a, r) => ({ ...a, [r.category]: (a[r.category] || 0) + r.expected_loss }), {})
  ).map(([name, value]) => ({ name, value: +(value / 10000).toFixed(1) })).sort((a, b) => b.value - a.value);

  return {
    pending: recs.length,
    d_day: recs.filter((r) => r.days_until_expiry === 0).length,
    d_1: recs.filter((r) => r.days_until_expiry === 1).length,
    d_2: recs.filter((r) => r.days_until_expiry === 2).length,
    risk_amount: risk,
    expected_revenue: Math.round(revenue),
    expected_waste_loss: Math.round(residual),
    by_category: byCat,
    waste_trend: [
      { day: "월", 폐기손실: 42, 절감: 12 }, { day: "화", 폐기손실: 38, 절감: 15 },
      { day: "수", 폐기손실: 33, 절감: 19 }, { day: "목", 폐기손실: 29, 절감: 22 },
      { day: "금", 폐기손실: 24, 절감: 27 }, { day: "토", 폐기손실: 19, 절감: 31 },
      { day: "일", 폐기손실: 15, 절감: 34 },
    ],
    context: { weather: "비", temp: 23, visitor_delta: -0.12, store_time: "18:24" },
    calendar: {
      today: "2026-07-20", today_label: "7월 20일 월요일",
      week: [
        { d: "월", date: 20, type: "today" },
        { d: "화", date: 21, type: "open" },
        { d: "수", date: 22, type: "open" },
        { d: "목", date: 23, type: "open" },
        { d: "금", date: 24, type: "open" },
        { d: "토", date: 25, type: "pre_closed" },
        { d: "일", date: 26, type: "closed" },
      ],
      next_closure: { date: "2026-07-26", label: "7월 26일(일)", days_left: 6, reason: "의무휴업 (4주 일요일)" },
      next_holiday: { date: "2026-08-15", label: "8월 15일(토)", days_left: 26, reason: "광복절" },
      pre_closure_lift: 0.21,
      rule: "의무휴업일에는 판매가 불가능하므로, 전일에는 D+1 상품까지 조기 처리 대상에 포함합니다.",
    },
  };
}

/* 재고 원장 — 추천 할인율은 마찬가지로 엔진이 계산합니다 */
const MOCK_INVENTORY_RAW = [
  { product_id: "P001", product_name: "한우 등심 300g",   category: "축산",   stock_quantity: 8,  days_until_expiry: 0, turnover: 0.42, cost: 38000, regular_price: 52000, esl_applicable: true },
  { product_id: "P002", product_name: "한우 채끝 300g",   category: "축산",   stock_quantity: 14, days_until_expiry: 3, turnover: 0.61, cost: 34000, regular_price: 46000, esl_applicable: true },
  { product_id: "P008", product_name: "닭가슴살 1kg",      category: "축산",   stock_quantity: 15, days_until_expiry: 1, turnover: 0.55, cost: 9800,  regular_price: 14500, esl_applicable: true },
  { product_id: "P014", product_name: "삼겹살 500g",       category: "축산",   stock_quantity: 12, days_until_expiry: 1, turnover: 0.72, cost: 13100, regular_price: 18650, esl_applicable: true },
  { product_id: "P019", product_name: "손질 오징어 2마리", category: "수산",   stock_quantity: 9,  days_until_expiry: 0, turnover: 0.38, cost: 5200,  regular_price: 8900,  esl_applicable: true },
  { product_id: "P020", product_name: "고등어 2마리",      category: "수산",   stock_quantity: 16, days_until_expiry: 2, turnover: 0.58, cost: 3900,  regular_price: 6200,  esl_applicable: true },
  { product_id: "P011", product_name: "국내산 사과 5입",   category: "청과",   stock_quantity: 14, days_until_expiry: 2, turnover: 0.66, cost: 8900,  regular_price: 12400, esl_applicable: true },
  { product_id: "P022", product_name: "모둠 쌈채소",       category: "청과",   stock_quantity: 11, days_until_expiry: 1, turnover: 0.70, cost: 2200,  regular_price: 3500,  esl_applicable: true },
  { product_id: "P042", product_name: "손질 대파 300g",    category: "청과",   stock_quantity: 22, days_until_expiry: 0, turnover: 0.81, cost: 1500,  regular_price: 2450,  esl_applicable: true },
  { product_id: "P027", product_name: "우유 1L",           category: "유제품", stock_quantity: 24, days_until_expiry: 2, turnover: 0.88, cost: 2100,  regular_price: 3130,  esl_applicable: true },
  { product_id: "P031", product_name: "플레인 요거트 4입", category: "유제품", stock_quantity: 18, days_until_expiry: 2, turnover: 0.74, cost: 2600,  regular_price: 3980,  esl_applicable: true },
  { product_id: "P036", product_name: "모듬 초밥 12P",     category: "즉석",   stock_quantity: 6,  days_until_expiry: 0, turnover: 0.69, cost: 8400,  regular_price: 13900, esl_applicable: false },
  { product_id: "P037", product_name: "김밥 2줄",          category: "즉석",   stock_quantity: 10, days_until_expiry: 0, turnover: 0.79, cost: 3200,  regular_price: 5500,  esl_applicable: false },
];

const MOCK_ESL = {
  sent_today: 86, applied: 84, failed: 2,
  logs: [
    { product_name: "한우 등심 300g", label_id: "A-1042", status: "failed", detail: "통신 시간 초과", action: "retry" },
    { product_name: "모듬 초밥 12P", label_id: "-", status: "manual", detail: "ESL 미적용 품목 · 수기 라벨 필요", action: "print" },
    { product_name: "삼겹살 500g", label_id: "A-0871", status: "ok", detail: "18:12 반영 완료", elapsed: "38초" },
    { product_name: "우유 1L", label_id: "A-0455", status: "ok", detail: "18:12 반영 완료", elapsed: "41초" },
    { product_name: "손질 대파 300g", label_id: "A-0912", status: "ok", detail: "18:13 반영 완료", elapsed: "36초" },
    { product_name: "플레인 요거트 4입", label_id: "A-0733", status: "ok", detail: "18:13 반영 완료", elapsed: "44초" },
  ],
};

const MOCK_KPI = {
  waste_rate: 0.031, waste_rate_before: 0.049,
  saved_amount: 12400000, saved_delta: 0.18, approval_rate: 0.91,
  conversion_delta: 0.41, decision_time_before: 30, decision_time_after: 1,
  monthly: [{ m: "3월", v: 98 }, { m: "4월", v: 90 }, { m: "5월", v: 73 }, { m: "6월", v: 57 }, { m: "7월", v: 41 }],
  rejected: { count: 8, wasted: 6, loss: 214000, could_save: 139000 },
  approval_breakdown: [{ name: "그대로 승인", value: 84 }, { name: "조정 후 승인", value: 7 }, { name: "반려", value: 9 }],
};

async function call(path, options) {
  const res = await fetch(BASE + path, {
    cache: "no-store",
    headers: { "Content-Type": "application/json", "Cache-Control": "no-cache" },
    ...options,
  });
  if (!res.ok) throw new Error(`API ${res.status}`);
  return res.json();
}

function latestPolicyRows(rows) {
  if (!Array.isArray(rows) || rows.length === 0) return [];
  const latestRequestId = rows[0].request_id;
  return rows.filter((row) => row.request_id === latestRequestId);
}

const inventoryCellKey = (item) => `${item.product_id}:${item.dte_index}`;

export async function login(id, pw, storeId) {
  if (USE_MOCK) {
    await delay(650);
    if (!id || !pw) throw new Error("아이디와 비밀번호를 입력해주세요.");
    if (pw.length < 4) throw new Error("비밀번호가 올바르지 않습니다.");
    return { user: { id, name: "임종욱", role: "신선1부문 관리자" }, stores: STORES, storeId: storeId ?? "S01" };
  }
  const result = await call("/login", { method: "POST", body: JSON.stringify({ id, pw, store_id: storeId }) });
  const stores = (result.stores ?? []).filter((store) => ACTIVE_STORE_IDS.has(store.store_id));
  return { ...result, stores, storeId: ACTIVE_STORE_IDS.has(result.storeId) ? result.storeId : "S01" };
}
export async function getStores() {
  if (USE_MOCK) { await delay(150); return STORES; }
  return (await call("/stores")).filter((store) => ACTIVE_STORE_IDS.has(store.store_id));
}
export async function getSummary(storeId) {
  if (USE_SUMMARY_MOCK) { await delay(600); return mockSummary(storeId); }
  const revision = Date.now();
  const [summary, inventory] = await Promise.all([
    call(`/summary?store_id=${encodeURIComponent(storeId)}&_=${revision}`),
    call(`/inventory?store_id=${encodeURIComponent(storeId)}&_=${revision}`),
  ]);
  const riskItems = inventory.filter((item) => item.days_until_expiry <= 2);
  const byCategory = new Map();
  const riskAmount = riskItems.reduce((total, item) => {
    const amount = item.stock_quantity * item.cost;
    byCategory.set(item.category, (byCategory.get(item.category) ?? 0) + amount);
    return total + amount;
  }, 0);
  return {
    ...summary,
    snapshot_date: inventory[0]?.snapshot_date ?? summary.snapshot_date,
    product_count: new Set(inventory.map((item) => item.product_id)).size,
    total_stock_quantity: inventory.reduce((total, item) => total + item.stock_quantity, 0),
    pending: riskItems.length,
    d_day: inventory.filter((item) => item.days_until_expiry <= 0).length,
    d_1: inventory.filter((item) => item.days_until_expiry === 1).length,
    d_2: inventory.filter((item) => item.days_until_expiry === 2).length,
    risk_amount: Math.round(riskAmount),
    by_category: [...byCategory]
      .map(([name, value]) => ({ name, value: +(value / 10000).toFixed(1) }))
      .sort((a, b) => b.value - a.value),
  };
}
export async function getRecommendations(storeId) {
  if (USE_RECOMMENDATIONS_MOCK) { await delay(700); return mockRecs(storeId); }
  const revision = Date.now();
  const [rawRecommendations, inventory] = await Promise.all([
    call(`/recommendations?store_id=${encodeURIComponent(storeId)}&_=${revision}`),
    call(`/inventory?store_id=${encodeURIComponent(storeId)}&_=${revision}`),
  ]);
  const recommendations = latestPolicyRows(rawRecommendations);
  const inventoryByCell = new Map(inventory.map((item) => [inventoryCellKey(item), item]));
  return recommendations.map((rec) => {
    const item = inventoryByCell.get(inventoryCellKey(rec)) ?? {};
    return {
      ...item,
      ...rec,
      days_until_expiry: rec.dte_index,
      stock_quantity: rec.initial_available_qty,
      expected_loss: rec.expected_waste_loss,
      sell_probability: rec.sell_through_rate,
      expected_gain: rec.expected_profit,
      recommendation_available: true,
      ai_reason: `예상 판매 ${rec.expected_sales_qty.toFixed(1)}개 · 예상 소진율 ${Math.round(rec.sell_through_rate * 100)}% · 예상 폐기손실 ${Math.round(rec.expected_waste_loss).toLocaleString()}원`,
    };
  });
}
export async function getInventory(storeId) {
  if (USE_INVENTORY_MOCK) {
    await delay(600);
    const policy = loadPolicy(storeId);
    return MOCK_INVENTORY_RAW.map((i) => withRecommendation(i, dayCap(i.days_until_expiry, policy), policy.max_discount));
  }
  const revision = Date.now();
  const [inventory, rawRecommendations] = await Promise.all([
    call(`/inventory?store_id=${encodeURIComponent(storeId)}&_=${revision}`),
    call(`/recommendations?store_id=${encodeURIComponent(storeId)}&_=${revision}`),
  ]);
  const recommendations = latestPolicyRows(rawRecommendations);
  const recommendationByCell = new Map(recommendations.map((rec) => [inventoryCellKey(rec), rec]));
  return inventory.map((item) => {
    const rec = recommendationByCell.get(inventoryCellKey(item));
    return rec ? {
      ...item,
      request_id: rec.request_id,
      dte_index: rec.dte_index,
      recommended_rate: rec.recommended_rate,
      recommendation_available: true,
      expected_loss: rec.expected_waste_loss,
      sell_probability: rec.sell_through_rate,
    } : {
      ...item,
      request_id: undefined,
      recommended_rate: 0,
      recommendation_available: false,
      sell_probability: 0,
    };
  });
}
function groupApprovalItems(items) {
  return items.reduce((groups, item) => {
    const group = groups.get(item.request_id) ?? [];
    group.push(item);
    groups.set(item.request_id, group);
    return groups;
  }, new Map());
}

function approvalPayload(items, finalize) {
  return {
    items: items.map((item) => ({
      product_id: item.product_id,
      dte_index: item.dte_index,
      approved_rate: item.approved_rate,
    })),
    ...(finalize === undefined ? {} : { finalize }),
  };
}

export async function approve(storeId, items, { finalize = true } = {}) {
  if (USE_RECOMMENDATIONS_MOCK) {
    await delay(900);
    return { approved: items.length, esl_sent: Math.max(items.length - 1, 0), esl_failed: items.length ? 1 : 0 };
  }
  const results = [];
  for (const [requestId, requestItems] of groupApprovalItems(items)) {
    results.push(await call(`/recommendations/${encodeURIComponent(requestId)}/approve`, {
      method: "POST",
      body: JSON.stringify(approvalPayload(requestItems, finalize)),
    }));
  }
  return { approved: results.reduce((sum, result) => sum + result.updated_items, 0), results };
}

export async function requestManagerApproval(storeId, items) {
  if (USE_RECOMMENDATIONS_MOCK) { await delay(450); return { requested: items.length }; }
  const results = [];
  for (const [requestId, requestItems] of groupApprovalItems(items)) {
    results.push(await call(`/recommendations/${encodeURIComponent(requestId)}/manager-request`, {
      method: "POST",
      body: JSON.stringify(approvalPayload(requestItems)),
    }));
  }
  return { requested: results.reduce((sum, result) => sum + result.requested_items, 0), results };
}

export async function approveByManager(storeId, items) {
  if (USE_RECOMMENDATIONS_MOCK) { await delay(700); return { approved: items.length }; }
  const results = [];
  for (const [requestId, requestItems] of groupApprovalItems(items)) {
    results.push(await call(`/recommendations/${encodeURIComponent(requestId)}/manager-approve`, {
      method: "POST",
      body: JSON.stringify(approvalPayload(requestItems)),
    }));
  }
  return { approved: results.reduce((sum, result) => sum + result.updated_items, 0), results };
}

export async function approveReprice(storeId, items) {
  if (USE_RECOMMENDATIONS_MOCK) { await delay(700); return { approved: items.length }; }
  const results = [];
  for (const [requestId, requestItems] of groupApprovalItems(items)) {
    results.push(await call(`/recommendations/${encodeURIComponent(requestId)}/reprice-approve`, {
      method: "POST",
      body: JSON.stringify(approvalPayload(requestItems)),
    }));
  }
  return { approved: results.reduce((sum, result) => sum + result.updated_items, 0), results };
}

export async function rejectRecommendation(requestId) {
  if (USE_RECOMMENDATIONS_MOCK) return { request_id: requestId, status: "REJECTED" };
  return call(`/recommendations/${encodeURIComponent(requestId)}/reject`, { method: "POST" });
}

/* ==================================================================
   반려 → AI 재추천 (2단 결재의 반려 분기)
   ------------------------------------------------------------------
   점장 반려는 프로세스의 "종료"가 아니라 "제약 추가"입니다.
   반려 사유를 제약조건으로 바꿔 프라이싱 엔진(recommendRate)을 같은
   목적함수로 다시 풀고, 낮아진 할인율을 담당자 재검토 대기열로 되돌립니다.

   무한 반복을 막기 위해 재추천은 MAX_REPRICE_ROUNDS 회까지만 허용하고,
   그 이후에는 ① 점장 수동 가격 지정 ② 할인 미적용(폐기 처리)로 강제
   종결합니다. 운영상 "결론이 나지 않는 건"이 남지 않게 하는 장치입니다.

   백엔드 연동 시 requestReprice 만 POST /recommendations/reprice 로
   바뀌며 화면 로직은 그대로입니다.
   ================================================================== */
export const MAX_REPRICE_ROUNDS = 2;

/* cut = 반려 사유가 부과하는 할인 상한 감폭(%p). 사유가 곧 제약조건입니다. */
export const REJECT_REASONS = [
  { code: "rate_too_high", label: "할인율 과다", desc: "상시 가격 신뢰도·마진 훼손 우려", cut: 6 },
  { code: "stock_ok",      label: "재고 여유",   desc: "당일 소진 압박이 크지 않음",       cut: 10 },
  { code: "promo_overlap", label: "행사 중복",   desc: "전단·멤버십 행사와 할인 중복",     cut: 12 },
  { code: "margin_guard",  label: "마진 방어",   desc: "원가 대비 역마진 구간 진입",       cut: 15 },
  { code: "etc",           label: "기타",        desc: "현장 판단 · 메모로 사유 기록",     cut: 5 },
];

/* 반려 사유를 상한 제약으로 환산해 순이익 최대점을 다시 찾습니다.
   manualCap 이 오면 사유 감폭 대신 그 값을 상한으로 씁니다. */
export function repriceUnderConstraint(item, { previousRate, reasonCode, policy, manualCap }) {
  const p = policy ?? DEFAULT_POLICY;
  const reason = REJECT_REASONS.find((r) => r.code === reasonCode) ?? REJECT_REASONS[0];
  const prev = Math.round(previousRate ?? (item.recommended_rate ?? 0) * 100);
  const dCap = dayCap(item.days_until_expiry, p);
  const cap = Math.max(0, Math.min(prev - 1, manualCap != null ? manualCap : prev - reason.cut, dCap));
  const rec = recommendRate(item, cap);
  const before = recommendRate(item, Math.min(prev, dCap));
  const gainDelta = rec.gain - before.gain;

  return {
    new_rate: rec.rate,
    cap,
    prob: rec.prob,
    price: rec.price,
    expected_net: rec.net,
    expected_gain: rec.gain,
    /* 반려로 포기한 순이익 — "왜 반려에 비용이 따르는가"를 숫자로 남깁니다 */
    gain_delta: gainDelta,
    needs_manager: rec.rate > p.two_step_over,
    reason_label: reason.label,
    ai_note:
      rec.rate === 0
        ? `${reason.label} 반영 · 상한 ${cap}% 구간에서는 할인 마진 손실이 폐기 손실보다 커 할인 미적용을 권고합니다.`
        : `${reason.label} 반영 · 할인 상한 ${prev}% → ${cap}% 재설정 후 순이익 최대점 재탐색 · ` +
          `${rec.rate}% 적용 시 예상 소진율 ${rec.prob}% · 미조치 대비 순이익 +${Math.round(rec.gain / 1000)}천원` +
          (gainDelta < 0 ? ` (직전안 대비 ${Math.round(gainDelta / 1000)}천원)` : ""),
  };
}

/* 재추천 요청 — entries: [{ item, previous_rate, reason_code, memo, round }] */
export async function requestReprice(storeId, entries) {
  if (USE_MOCK) {
    await delay(1500);
    const policy = loadPolicy(storeId);
    return entries.map((e) => ({
      product_id: e.item.product_id,
      round: e.round,
      previous_rate: e.previous_rate,
      reason_code: e.reason_code,
      memo: e.memo ?? "",
      ...repriceUnderConstraint(e.item, {
        previousRate: e.previous_rate, reasonCode: e.reason_code, policy,
      }),
    }));
  }
  const grouped = entries.reduce((groups, entry) => {
    const requestId = entry.item.request_id;
    if (!requestId) throw new Error("재추천 원본 request_id가 없습니다.");
    const group = groups.get(requestId) ?? [];
    group.push(entry);
    groups.set(requestId, group);
    return groups;
  }, new Map());
  const results = [];
  for (const [requestId, requestEntries] of grouped) {
    results.push(...await call(`/recommendations/${encodeURIComponent(requestId)}/reprice`, {
      method: "POST",
      body: JSON.stringify({
        store_id: storeId,
        items: requestEntries.map((e) => ({
          product_id: e.item.product_id,
          dte_index: e.item.dte_index,
          previous_rate: e.previous_rate / 100,
          reason_code: e.reason_code,
          memo: e.memo ?? "",
          round: e.round,
        })),
      }),
    }));
  }
  return results;
}

/* 강제 종결 기록 — 수동 가격 지정 / 할인 미적용(폐기 처리) */
export async function closeRepriceFlow(storeId, payload) {
  if (USE_MOCK) { await delay(500); return { ok: true, ...payload }; }
  return call("/recommendations/close", {
    method: "POST", body: JSON.stringify({ store_id: storeId, ...payload }),
  });
}

export async function getEslStatus(storeId) {
  if (USE_MOCK) { await delay(500); return MOCK_ESL; }
  return call(`/esl/status?store_id=${storeId}`);
}
export async function getKpi(storeId, period = "month") {
  if (USE_MOCK) { await delay(650); return MOCK_KPI; }
  return call(`/kpi?store_id=${storeId}&period=${period}`);
}

/* ---------- 승인 이력 ---------- */
/* 다이나믹 프라이싱 이력 — 추천·승인 모두 1%p 단위이며, approver 열은 결재 단계를 남깁니다 */
const MOCK_HISTORY = [
  { id: "H231", date: "2026-07-20 08:34", user: "임종욱", approver: "점장 김현수", product_name: "한우 등심 300g",   category: "축산",   recommended_rate: 0.36, approved_rate: 0.36, result: "sold",    sold_qty: 7,  stock_quantity: 8,  revenue: 232960 },
  { id: "H230", date: "2026-07-20 08:34", user: "임종욱", approver: "-",           product_name: "삼겹살 500g",       category: "축산",   recommended_rate: 0.30, approved_rate: 0.24, result: "partial", sold_qty: 7,  stock_quantity: 12, revenue: 99190 },
  { id: "H229", date: "2026-07-20 08:34", user: "임종욱", approver: "-",           product_name: "우유 1L",           category: "유제품", recommended_rate: 0.16, approved_rate: 0.16, result: "sold",    sold_qty: 22, stock_quantity: 24, revenue: 57860 },
  { id: "H228", date: "2026-07-19 19:02", user: "박신선", approver: "점장 김현수", product_name: "손질 오징어 2마리", category: "수산",   recommended_rate: 0.33, approved_rate: 0.33, result: "sold",    sold_qty: 8,  stock_quantity: 9,  revenue: 47680 },
  { id: "H227", date: "2026-07-19 19:02", user: "박신선", approver: "-",           product_name: "모듬 초밥 12P",     category: "즉석",   recommended_rate: 0.30, approved_rate: 0.18, result: "wasted",  sold_qty: 3,  stock_quantity: 6,  revenue: 34200 },
  { id: "H226", date: "2026-07-19 08:31", user: "임종욱", approver: "-",           product_name: "국내산 사과 5입",   category: "청과",   recommended_rate: 0.18, approved_rate: 0.18, result: "sold",    sold_qty: 11, stock_quantity: 14, revenue: 111870 },
  { id: "H225", date: "2026-07-19 08:31", user: "임종욱", approver: "반려",        product_name: "닭가슴살 1kg",      category: "축산",   recommended_rate: 0.31, approved_rate: 0.22, result: "wasted",  sold_qty: 6,  stock_quantity: 15, revenue: 67860 },
  { id: "H224", date: "2026-07-18 19:14", user: "박신선", approver: "-",           product_name: "모둠 쌈채소",       category: "청과",   recommended_rate: 0.23, approved_rate: 0.23, result: "sold",    sold_qty: 10, stock_quantity: 11, revenue: 26950 },
  { id: "H223", date: "2026-07-18 08:29", user: "임종욱", approver: "-",           product_name: "플레인 요거트 4입", category: "유제품", recommended_rate: 0.16, approved_rate: 0.09, result: "partial", sold_qty: 12, stock_quantity: 18, revenue: 43450 },
  { id: "H222", date: "2026-07-18 08:29", user: "임종욱", approver: "-",           product_name: "고등어 2마리",      category: "수산",   recommended_rate: 0.26, approved_rate: 0.26, result: "sold",    sold_qty: 14, stock_quantity: 16, revenue: 64230 },
];

export async function getHistory(storeId) {
  if (USE_MOCK) { await delay(600); return MOCK_HISTORY; }
  return call(`/history?store_id=${storeId}`);
}

/* ---------- 본사 뷰 ---------- */
const MOCK_HQ = {
  total_saved: 32300000, total_stores: 3, avg_waste_rate: 0.034, adoption_rate: 0.89,
  stores: [
    { store_id: "S01", name: "롯데마트 서울역점", area: "복합", waste_rate: 0.031, saved: 12400000, approval_rate: 0.91, pending: 10, trend: -1.8 },
    { store_id: "S02", name: "롯데마트 양평점", area: "주거", waste_rate: 0.029, saved: 10800000, approval_rate: 0.94, pending: 9, trend: -2.1 },
    { store_id: "S03", name: "롯데마트 잠실점", area: "오피스", waste_rate: 0.042, saved: 9100000, approval_rate: 0.82, pending: 8, trend: -0.9 },
  ],
  rollout: [
    { phase: "파일럿", stores: 3, status: "done", desc: "수도권 3개점 · 3개월" },
    { phase: "확산 1차", stores: 30, status: "current", desc: "수도권 전 점포" },
    { phase: "확산 2차", stores: 110, status: "planned", desc: "전국 롯데마트" },
  ],
  monthly_total: [
    { m: "3월", v: 21 }, { m: "4월", v: 26 }, { m: "5월", v: 31 }, { m: "6월", v: 36 }, { m: "7월", v: 41 },
  ],
};

export async function getHqOverview() {
  if (USE_MOCK) { await delay(700); return MOCK_HQ; }
  return call("/hq/overview");
}

/* ---------- 알림 ---------- */
const MOCK_NOTIFICATIONS = [
  { id: 1, type: "danger", title: "D-Day 상품 3건 신규 탐지", desc: "축산 2건 · 수산 1건 · 폐기위험 8.2만원", time: "5분 전" },
  { id: 2, type: "warning", title: "ESL 전송 실패 1건", desc: "한우 등심 300g · 라벨 A-1042 통신 오류", time: "22분 전" },
  { id: 3, type: "info", title: "AI 추천 배치 완료", desc: "10건 생성 · 예상 회수 21.1만원", time: "08:32" },
  { id: 4, type: "info", title: "주간 리포트가 준비되었습니다", desc: "폐기율 3.1% · 지난주 대비 −1.8%p", time: "어제" },
];

export async function getNotifications(storeId) {
  if (USE_MOCK) { await delay(350); return MOCK_NOTIFICATIONS; }
  return call(`/notifications?store_id=${storeId}`);
}

/* ---------- 정책 설정 ---------- */
/* 2단 결재 임계값: 이 값을 초과하는 할인은 담당자 승인 후 점장 최종 승인이 필요합니다
   실제 기준값은 점포별로 저장되는 policy.two_step_over 입니다 — App이 이 값을 읽어
   승인 로직에 씁니다. 이 상수는 정책을 아직 한 번도 저장하지 않은 곳(참고용 문구 등)을 위한
   기본값일 뿐이며, 승인 로직의 실제 근거는 더 이상 이 상수가 아닙니다. */
export const APPROVAL_THRESHOLD = 30;

export const DEFAULT_POLICY = {
  /* 스키마 버전 — 코드 기본값을 바꿀 때 올립니다.
     저장된 정책의 버전이 다르면 폐기하고 새 기본값을 씁니다.
     (이게 없으면 예전에 저장한 상한이 새 기본값을 영영 덮어써서,
      "이 노트북에서만 추천이 이상하게 나오는" 상황이 생깁니다) */
  schema: 2,
  max_discount: 40,
  two_step_over: 30,
  /* 잔여일별 할인 상한(고정 할인율이 아님) — AI는 이 범위 안에서 1%p 단위로 최적점을 찾습니다 */
  step_d2: 25, step_d1: 35, step_d0: 40,
  closing_hour: 20,
  auto_approve_under: 0,
  notify_esl_fail: true,
  notify_new_risk: true,
};

const policyKey = (storeId) => `fw_policy_${storeId}`;

/* 점포별로 저장된 정책을 읽습니다. 저장된 적 없거나 스키마가 낡았으면 기본값. */
export function loadPolicy(storeId) {
  try {
    const raw = localStorage.getItem(policyKey(storeId));
    if (raw) {
      const saved = JSON.parse(raw);
      if (saved.schema === DEFAULT_POLICY.schema) return { ...DEFAULT_POLICY, ...saved };
      /* 구버전 저장값은 폐기합니다 — 새 기본값이 적용되지 않는 문제를 막습니다 */
      localStorage.removeItem(policyKey(storeId));
    }
  } catch { /* localStorage 접근 불가 시 기본값으로 폴백 */ }
  return { ...DEFAULT_POLICY };
}

/* 정책이 바뀌면 값이 달라져야 하는 화면들의 useAsync 의존성 키 */
export const policyDep = (p) =>
  p ? `${p.max_discount}|${p.step_d0}|${p.step_d1}|${p.step_d2}|${p.two_step_over}|${p.auto_approve_under}` : "";

export async function savePolicy(storeId, policy) {
  const next = { ...policy, schema: DEFAULT_POLICY.schema };
  try { localStorage.setItem(policyKey(storeId), JSON.stringify(next)); } catch { /* 저장 실패해도 세션 내 상태는 반영됨 */ }
  if (USE_MOCK) { await delay(600); return { ok: true, policy: next }; }
  return call("/policy", { method: "POST", body: JSON.stringify({ store_id: storeId, ...next }) });
}

/* ---------- 역할(권한) ---------- */
export const ROLES = {
  staff:   { key: "staff",   label: "신선팀 담당자", scope: ["home", "inv", "hist", "perf"], canPolicy: false, canAuto: false },
  manager: { key: "manager", label: "점장",         scope: ["home", "inv", "hist", "perf"], canPolicy: true,  canAuto: true },
  hq:      { key: "hq",      label: "본사 운영팀",   scope: ["home", "inv", "hist", "perf", "hq", "esg", "ab", "sim"], canPolicy: true, canAuto: true },
};

/* ---------- ESG · 탄소 환산 ---------- */
/* 계수 출처: Eriksson et al.(2015) 슈퍼마켓 식품폐기물 탄소발자국 · 카테고리별 kgCO2e/kg */
export const CARBON_FACTOR = { 축산: 27.0, 수산: 6.1, 유제품: 1.9, 청과: 0.9, 즉석: 3.4 };

const MOCK_ESG = {
  saved_waste_kg: 4820,
  saved_co2e_kg: 41300,
  months: [
    { m: "3월", co2e: 5.1, waste: 0.72 }, { m: "4월", co2e: 6.4, waste: 0.81 },
    { m: "5월", co2e: 8.2, waste: 0.94 }, { m: "6월", co2e: 9.8, waste: 1.11 },
    { m: "7월", co2e: 11.8, waste: 1.24 },
  ],
  by_category: [
    { name: "축산", waste_share: 21, co2_share: 58, co2e: 23954 },
    { name: "수산", waste_share: 12, co2_share: 14, co2e: 5782 },
    { name: "즉석", waste_share: 14, co2_share: 11, co2e: 4543 },
    { name: "유제품", waste_share: 23, co2_share: 10, co2e: 4130 },
    { name: "청과", waste_share: 30, co2_share: 7, co2e: 2891 },
  ],
  equivalents: { trees: 4589, car_km: 217368, households: 12 },
  target: { name: "롯데마트 2025 폐기 감축목표", goal: 0.30, current: 0.19 },
};

export async function getEsg(scope = "store") {
  if (USE_MOCK) {
    await delay(650);
    if (scope === "hq") {
      return {
        ...MOCK_ESG,
        saved_waste_kg: MOCK_ESG.saved_waste_kg * 4,
        saved_co2e_kg: MOCK_ESG.saved_co2e_kg * 4,
        equivalents: { trees: 18356, car_km: 869472, households: 48 },
      };
    }
    return MOCK_ESG;
  }
  return call(`/esg?scope=${scope}`);
}

/* ---------- 효과 검증 (A/B) ---------- */
const MOCK_AB = {
  period: "2026-05-01 ~ 2026-07-20 (12주)",
  design: "수도권 3개점 중 2개점 적용(처치군) · 1개점 미적용(대조군) · 상권·매출규모 매칭",
  treatment: { stores: ["서울역점", "양평점"], waste_rate: 0.030, margin_rate: 0.121, conversion: 0.68 },
  control: { stores: ["잠실점"], waste_rate: 0.047, margin_rate: 0.118, conversion: 0.44 },
  weekly: [
    { w: "1주", 적용: 4.6, 대조: 4.8 }, { w: "2주", 적용: 4.3, 대조: 4.9 },
    { w: "3주", 적용: 4.0, 대조: 4.7 }, { w: "4주", 적용: 3.8, 대조: 4.8 },
    { w: "5주", 적용: 3.6, 대조: 4.6 }, { w: "6주", 적용: 3.4, 대조: 4.9 },
    { w: "7주", 적용: 3.3, 대조: 4.7 }, { w: "8주", 적용: 3.2, 대조: 4.8 },
    { w: "9주", 적용: 3.1, 대조: 4.7 }, { w: "10주", 적용: 3.0, 대조: 4.8 },
    { w: "11주", 적용: 3.0, 대조: 4.7 }, { w: "12주", 적용: 3.0, 대조: 4.7 },
  ],
  lift: { waste: -0.362, margin: 0.025, conversion: 0.545 },
  significance: { p_value: 0.003, ci: "-4.7%p ~ -2.1%p", n: 2184 },
  benchmark: "Sanders(2024) 다이나믹 프라이싱 실증: 폐기 −20.8% · 이익 +2.9%",
};

export async function getAbTest() {
  if (USE_MOCK) { await delay(700); return MOCK_AB; }
  return call("/experiments/ab");
}

/* ---------- 본사 정책 시뮬레이터 ---------- */
export function simulatePolicy({ maxDiscount = 40, startDay = 2, autoApprove = 0, stores = 110 }) {
  /* 반응모형을 상품 단위 로지스틱과 같은 형태로 맞춥니다 —
     상한을 올릴수록 소진율이 오르지만 수확체감(포화)하고, 마진은 선형으로 깎입니다. */
  const base = { wastePerStore: 84.5, wasteCostPerTon: 1470000, marginRate: 0.197 };
  const POOL_R50 = 19;   // 전 카테고리 가중평균 반응 중점(%)
  const POOL_K = 0.19;   // 전 카테고리 가중평균 반응 기울기
  const logistic = (r) => 1 / (1 + Math.exp(-POOL_K * (r - POOL_R50)));
  /* 스케일 0.29 = 현행 정책(상한 40% · D-2 시작)에서 기존 추정치와 동일한 소진 개선폭이
     나오도록 보정한 값입니다. 상한을 더 올려도 포화되어 효과가 거의 늘지 않습니다. */
  const sellLift = Math.min(0.55, (logistic(maxDiscount) - logistic(0)) * 0.29 + (startDay - 1) * 0.06);
  const marginDrop = (maxDiscount / 100) * 0.42 + (startDay - 1) * 0.03;
  const autoBonus = autoApprove > 0 ? 0.04 : 0;

  const wasteReduction = Math.max(0, Math.min(0.62, sellLift + autoBonus));
  const wasteTon = base.wastePerStore * (1 - wasteReduction);
  const savedCost = (base.wastePerStore - wasteTon) * base.wasteCostPerTon;
  const marginLoss = 3041702181 / 110 * marginDrop * 0.55;
  const netPerStore = savedCost - marginLoss;
  return {
    wasteReduction,
    wasteTon: +wasteTon.toFixed(1),
    savedPerStore: Math.round(savedCost),
    marginLossPerStore: Math.round(marginLoss),
    netPerStore: Math.round(netPerStore),
    netTotal: Math.round(netPerStore * stores),
    co2eTon: +((base.wastePerStore - wasteTon) * 2.4).toFixed(1),
  };
}

/* ---------- AI 미추천 사유 ---------- */
export async function getSkipped(storeId) {
  if (USE_RECOMMENDATIONS_MOCK) {
    await delay(450);
    return [
      { product_id: "P002", dte_index: 3, product_name: "한우 채끝 300g", category: "축산", reason: "잔여 3일 · 예상 소진율 92%로 조치 불필요", type: "ok", comparison: { ai_candidate: { discount_rate: 0, expected_profit: 184000 }, no_discount: { discount_rate: 0, expected_profit: 191000 }, standard_markdown: { discount_rate: 0, expected_profit: 191000 } } },
      { product_id: "P020", dte_index: 3, product_name: "고등어 2마리", category: "수산", reason: "잔여 2일 · 회전율 정상 범위", type: "ok", comparison: { ai_candidate: { discount_rate: 0.02, expected_profit: 72000 }, no_discount: { discount_rate: 0, expected_profit: 76000 }, standard_markdown: { discount_rate: 0, expected_profit: 76000 } } },
      { product_id: "P055", dte_index: 3, product_name: "즉석 도시락", category: "즉석", reason: "재고 2개 미만 · 할인 효과 대비 관리비용 큼", type: "skip", comparison: { ai_candidate: { discount_rate: 0.02, expected_profit: 11800 }, no_discount: { discount_rate: 0, expected_profit: 12600 }, standard_markdown: { discount_rate: 0, expected_profit: 12600 } } },
      { product_id: "P061", dte_index: 3, product_name: "수입 체리 500g", category: "청과", reason: "행사 진행 중 · 중복 할인 방지 규칙 적용", type: "block", comparison: { ai_candidate: { discount_rate: 0.08, expected_profit: 68000 }, no_discount: { discount_rate: 0, expected_profit: 71000 }, standard_markdown: { discount_rate: 0, expected_profit: 71000 } } },
    ];
  }
  const revision = Date.now();
  const [skipped, inventory] = await Promise.all([
    call(`/recommendations/skipped?store_id=${encodeURIComponent(storeId)}&_=${revision}`),
    call(`/inventory?store_id=${encodeURIComponent(storeId)}&_=${revision}`),
  ]);
  const inventoryByCell = new Map(inventory.map((item) => [inventoryCellKey(item), item]));
  return skipped.map((item) => ({
    ...inventoryByCell.get(inventoryCellKey(item)),
    ...item,
  }));
}

export async function getCompleted(storeId) {
  if (USE_RECOMMENDATIONS_MOCK) return [];
  const revision = Date.now();
  const [completed, inventory] = await Promise.all([
    call(`/recommendations/completed?store_id=${encodeURIComponent(storeId)}&_=${revision}`),
    call(`/inventory?store_id=${encodeURIComponent(storeId)}&_=${revision}`),
  ]);
  const inventoryByCell = new Map(inventory.map((item) => [inventoryCellKey(item), item]));
  return completed.map((item) => ({
    ...inventoryByCell.get(inventoryCellKey(item)),
    ...item,
    days_until_expiry: item.dte_index,
  }));
}

export async function getManagerPending(storeId) {
  if (USE_RECOMMENDATIONS_MOCK) return [];
  const revision = Date.now();
  const [pending, inventory] = await Promise.all([
    call(`/recommendations/manager-pending?store_id=${encodeURIComponent(storeId)}&_=${revision}`),
    call(`/inventory?store_id=${encodeURIComponent(storeId)}&_=${revision}`),
  ]);
  const inventoryByCell = new Map(inventory.map((item) => [inventoryCellKey(item), item]));
  return pending.map((item) => ({
    ...inventoryByCell.get(inventoryCellKey(item)),
    ...item,
    days_until_expiry: item.dte_index,
    rate: Math.round(item.approved_rate * 100),
  }));
}

export async function getRepricePending(storeId) {
  if (USE_RECOMMENDATIONS_MOCK) return [];
  return call(`/recommendations/reprice-pending?store_id=${encodeURIComponent(storeId)}&_=${Date.now()}`);
}

/* ---------- 모델 성능 ---------- */
export async function getModelPerf() {
  if (USE_MOCK) {
    await delay(500);
    return {
      version: "v1.3.2", trained_at: "2026-07-14",
      mape: 0.147, mape_before: 0.221, hit_rate: 0.83, adoption: 0.91,
      drift: "정상", next_train: "2026-07-28",
      by_cat: [
        { name: "축산", mape: 0.132 }, { name: "수산", mape: 0.186 }, { name: "청과", mape: 0.164 },
        { name: "유제품", mape: 0.098 }, { name: "즉석", mape: 0.211 },
      ],
    };
  }
  return call("/model/performance");
}

/* ==================================================================
   다이나믹 프라이싱 엔진 (A모델 프론트 근사)
   ------------------------------------------------------------------
   기존 구현은 "30% 미만은 반응 0"이라는 계단함수를 써서 최적 할인율이
   항상 30% 이상으로 고정됐습니다. 그 결과 (1) 추천이 20/30/40% 세 값으로만
   찍히고 (2) 모든 건이 2단 결재 대상이 되어 결재 체계가 무의미해졌습니다.

   이번 버전은 A모델(판매량 예측 → 폐기량 예측 → 후보 할인율 시뮬레이션 →
   순이익 최대화)과 동일한 구조를 프론트에서 1%p 단위로 재현합니다.

     ① 수요반응   p(r) = p0 + (pMax - p0) / (1 + e^(-k(r - r50)))
     ② 잔여가치   미판매분은 잔여일수만큼 이월 판매 가치(salvage)를 가짐
     ③ 목적함수   net(r) = 판매량×(할인가 - 원가) - 미판매량×(폐기손실)
     ④ 최적해     r* = argmax net(r),  r ∈ {0,1,2,…,상한}, 동점 시 최소 r

   근거
   - 카테고리별 가격탄력성·부패지수: 자체 합성패널(fresh_daily_panel) 설계 전제
   - 축산·수산의 높은 준거가격(반응 중점이 높음): 현직자 인터뷰(2026-07-09)
   - 할인 상한 40%: 본사 지침 (현직자 인터뷰)
   - 폐기 처리단가 147,000원/톤: 기후에너지환경부고시 제2025-165호
   ================================================================== */

/* r50 = 절반 반응에 도달하는 할인율(%) · k = 반응 기울기 · p0 = 무할인 소진율 기준
   weightKg = 단위당 평균 중량(폐기 처리비 산정용) */
export const CATEGORY_RESPONSE = {
  유제품: { r50: 12, k: 0.22, p0: 0.50, pMax: 0.97, weightKg: 0.8 },
  청과:   { r50: 15, k: 0.20, p0: 0.45, pMax: 0.96, weightKg: 0.4 },
  즉석:   { r50: 18, k: 0.24, p0: 0.36, pMax: 0.95, weightKg: 0.35 },
  수산:   { r50: 20, k: 0.20, p0: 0.34, pMax: 0.93, weightKg: 0.5 },
  축산:   { r50: 22, k: 0.19, p0: 0.32, pMax: 0.94, weightKg: 0.4 },
};
const DEFAULT_RESPONSE = { r50: 18, k: 0.21, p0: 0.42, pMax: 0.95, weightKg: 0.45 };

const WASTE_COST_PER_KG = 147; // 147,000원/톤 (기후에너지환경부고시 제2025-165호)

/* 미판매 재고의 잔존가치 — D-Day는 전량 폐기, 잔여일이 남으면 이월 판매 가능.
   단 이월분도 하루 늙기 때문에 잔존가치는 1이 아닙니다. */
export const SALVAGE_BY_DAY = { 0: 0, 1: 0.40, 2: 0.62, 3: 0.75 };
const salvageOf = (d) => SALVAGE_BY_DAY[d] ?? 0.8;

export function responseParams(item) {
  const base = CATEGORY_RESPONSE[item.category] ?? DEFAULT_RESPONSE;
  const d = item.days_until_expiry ?? 0;
  /* 신선도 하락 보정 — 유통기한이 임박할수록 같은 할인율에서 반응이 둔해집니다.
     (합성패널 전제 3: "신선도 낮으면 할인해도 구매 안 함") */
  const freshnessPenalty = 3 * (1 - Math.min(d, 2) / 2);
  /* 회전율이 좋은 상품은 무할인 소진율 자체가 높습니다 */
  const turnoverLift = item.turnover != null ? (item.turnover - 0.6) * 0.25 : 0;
  return {
    ...base,
    r50: base.r50 + freshnessPenalty,
    p0: Math.max(0.1, Math.min(base.p0 + turnoverLift, base.pMax - 0.05)),
  };
}

/* 할인율 r(%) 에서의 예상 소진율 */
export function sellThrough(item, r) {
  const { r50, k, p0, pMax } = responseParams(item);
  return p0 + (pMax - p0) / (1 + Math.exp(-k * (r - r50)));
}

export function disposalFeePerUnit(item) {
  const { weightKg } = CATEGORY_RESPONSE[item.category] ?? DEFAULT_RESPONSE;
  return Math.round(weightKg * WASTE_COST_PER_KG);
}

/* ---------- 할인율별 기대 손익 곡선 (0~상한, 1%p 단위) ---------- */
export function profitCurve(item, maxRate = DEFAULT_POLICY.max_discount) {
  const salvage = salvageOf(item.days_until_expiry);
  const fee = disposalFeePerUnit(item);
  const rows = [];
  for (let r = 0; r <= maxRate; r += 1) {
    const p = sellThrough(item, r);
    const price = Math.round((item.regular_price * (1 - r / 100)) / 10) * 10;
    const sold = item.stock_quantity * p;
    const unsold = item.stock_quantity - sold;
    /* 미판매분 손실 = (원가 + 폐기처리비) × (1 - 잔존가치) */
    const lossPerUnsold = (item.cost + fee) * (1 - salvage);
    const net = sold * (price - item.cost) - unsold * lossPerUnsold;
    rows.push({ rate: r, net: Math.round(net), sold: +sold.toFixed(1), price, prob: +(p * 100).toFixed(0) });
  }
  return rows;
}

/* ---------- 최적 할인율 (순이익 최대화 · 동점 시 최소 할인) ---------- */
export function recommendRate(item, maxRate = DEFAULT_POLICY.max_discount) {
  const curve = profitCurve(item, maxRate);
  let best = curve[0];
  for (const row of curve) if (row.net > best.net) best = row;
  return {
    rate: best.rate,
    net: best.net,
    prob: best.prob,
    sold: best.sold,
    price: best.price,
    gain: best.net - curve[0].net,   // 미조치(0%) 대비 개선액
    curve,
  };
}

/* 목 데이터 행에 AI 추천 결과를 주입합니다 — 화면·모델이 같은 수식을 씁니다.
   cap     : 잔여일별 정책 상한 (여기서 잘립니다)
   ceiling : 본사 전사 상한 — 정책 제약이 없었다면 모델이 뭘 골랐을지 비교용 */
export function withRecommendation(item, cap = DEFAULT_POLICY.max_discount, ceiling = DEFAULT_POLICY.max_discount) {
  const rec = recommendRate(item, cap);
  const free = cap >= ceiling ? rec : recommendRate(item, ceiling);
  const cappedByPolicy = free.rate > rec.rate;
  const d = item.days_until_expiry ?? 0;
  const dayLabel = d === 0 ? "당일 폐기 예정" : `잔여 ${d}일`;
  const salvage = salvageOf(d);
  const reason =
    rec.rate === 0
      ? `${dayLabel} · 무할인 예상 소진율 ${Math.round(sellThrough(item, 0) * 100)}%로 할인 시 마진 손실이 폐기 손실보다 큼 · 조치 불필요`
      : `${dayLabel} · ${rec.rate}% 할인 시 예상 소진율 ${rec.prob}% · 미조치 대비 순이익 +${Math.round(rec.gain / 1000)}천원` +
        (salvage > 0 ? ` · 미판매분 이월 잔존가치 ${Math.round(salvage * 100)}% 반영` : " · 미판매분 전량 폐기 전제");
  return {
    ...item,
    recommended_rate: rec.rate / 100,
    sell_probability: +(rec.prob / 100).toFixed(2),
    expected_loss: Math.round(item.stock_quantity * item.cost),
    expected_gain: rec.gain,
    expected_net: rec.net,
    /* 정책 상한이 모델 추천을 잘랐는지 — 화면에 "상한 적용" 배지로 표시합니다 */
    capped_by_policy: cappedByPolicy,
    uncapped_rate: free.rate / 100,
    uncapped_gain: free.gain,
    policy_cap: cap,
    reason: item.reason_override ?? reason +
      (cappedByPolicy ? ` · 정책 상한 ${cap}%에 걸림(모델 권장 ${free.rate}%)` : ""),
  };
}

/* ==================================================================
   마감 가격 경로 (다이나믹 프라이싱의 시간축)
   ------------------------------------------------------------------
   승인은 "지금 몇 %"가 아니라 "마감까지 어떤 경로로 내려갈지"를 확정합니다.
   추천값에서 출발해 마감 시각에 잔여일별 상한(목표가)에 도달하도록
   1%p씩 나눕니다.

   ESL 전송은 매 스텝마다 하지 않습니다 — 직전 전송가 대비 3%p 이상
   벌어질 때만 보냅니다. 1%p 단위 추천이 ESL 배터리 수명을 갉아먹는
   문제에 대한 가드레일입니다. (docs/인프라_영향검토_1%p전환.md)
   ================================================================== */
export const MIN_STEP_GAP_MIN = 15;   // 가격 변경 최소 간격(분)
export const ESL_MIN_DELTA = 3;       // ESL 전송 최소 변동폭(%p)

export function pricePath(item, { startMin, closeMin, cap, earliestMin }) {
  const r0 = Math.round((item.recommended_rate ?? 0) * 100);
  const target = Math.min(cap ?? DEFAULT_POLICY.max_discount, DEFAULT_POLICY.max_discount);
  const total = target - r0;
  /* 잔여일이 남은 상품은 오늘 다 팔 이유가 없습니다 — 목적함수와 같은 논리로
     마감 인하 대상은 D-Day 상품뿐입니다. */
  const eligible = (item.days_until_expiry ?? 0) === 0;
  if (!eligible || total <= 0 || closeMin <= startMin) {
    return { flat: true, reason: !eligible ? "잔여일 보유" : "이미 상한", r0, target: r0, steps: [], startMin, closeMin };
  }
  /* 정확히 1%p씩 내리려면 total번의 인하가 필요하고, 최소 간격을 지키려면
     total × MIN_GAP 만큼의 시간이 있어야 합니다. 기본 시작 시각으로 부족하면
     마감 모드 진입 시각(earliestMin)까지 앞당깁니다.
     인하폭이 큰 품목일수록 일찍 시작하는 것이 현장 감각과도 맞습니다. */
  const need = total * MIN_STEP_GAP_MIN;
  const floorMin = earliestMin ?? startMin;
  const effStart = Math.max(floorMin, Math.min(startMin, closeMin - need));
  const span = closeMin - effStart;
  const slots = Math.max(1, Math.floor(span / MIN_STEP_GAP_MIN));
  const n = Math.min(total, slots);                    // 실제 인하 횟수
  const gap = Math.floor(span / n);
  startMin = effStart;
  const steps = [];
  let lastSent = r0;
  for (let k = 1; k <= n; k += 1) {
    const rate = r0 + Math.round((total * k) / n);
    const esl = rate - lastSent >= ESL_MIN_DELTA || k === n;
    if (esl) lastSent = rate;
    steps.push({
      min: startMin + gap * k,
      rate,
      price: Math.round((item.regular_price * (1 - rate / 100)) / 10) * 10,
      esl,
    });
  }
  return { flat: false, r0, target, gapMin: gap, stepPp: +(total / n).toFixed(1), eslCount: steps.filter((s) => s.esl).length, steps, startMin, closeMin };
}

/* 특정 시각(분)에서의 할인율 */
export function rateAt(path, nowMin) {
  let r = path.r0;
  for (const s of path.steps) if (nowMin >= s.min) r = s.rate;
  return r;
}

/* 다음 인하 스텝 */
export function nextStep(path, nowMin) {
  return path.steps.find((s) => s.min > nowMin) ?? null;
}

export async function getForecast(productId) {
  if (USE_MOCK) {
    await delay(400);
    const base = [12, 14, 11, 13, 18, 24, 21];
    return base.map((v, i) => ({
      day: ["월", "화", "수", "목", "금", "토", "일"][i],
      실제: i < 4 ? v : null,
      예측: Math.round(v * (0.95 + (i % 3) * 0.04)),
    }));
  }
  return call(`/forecast?product_id=${productId}`);
}
