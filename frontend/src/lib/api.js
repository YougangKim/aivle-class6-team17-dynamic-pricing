/* ------------------------------------------------------------------
   API 레이어 — 백엔드 완성 전까지 목(mock)으로 동작합니다.
   USE_MOCK 를 false 로 바꾸면 실제 서버를 호출합니다.
   ------------------------------------------------------------------ */
export const USE_MOCK = true;
const BASE = "/api";
const delay = (ms) => new Promise((r) => setTimeout(r, ms));

const STORES = [
  { store_id: "S01", name: "롯데마트 서울역점", area_type: "complex" },
  { store_id: "S02", name: "롯데마트 양평점", area_type: "residence" },
  { store_id: "S03", name: "롯데마트 잠실점", area_type: "office" },
  { store_id: "S04", name: "롯데마트 청량리점", area_type: "residence" },
];

const BASE_RECS = [
  { product_id: "P001", product_name: "한우 등심 300g", category: "축산", days_until_expiry: 0, stock_quantity: 8, cost: 38000, regular_price: 52000, recommended_rate: 0.4, expected_loss: 304000, sell_probability: 0.78, esl_applicable: true, reason: "오늘 미판매 시 폐기 손실 30.4만원 · 40% 할인 시 판매확률 78% · 최근 4주 동일 조건 소진율 82%" },
  { product_id: "P014", product_name: "삼겹살 500g", category: "축산", days_until_expiry: 1, stock_quantity: 12, cost: 13100, regular_price: 18650, recommended_rate: 0.3, expected_loss: 157200, sell_probability: 0.71, esl_applicable: true, reason: "미판매 시 손실 15.7만원 · 30% 할인 시 판매확률 71% · 주말 진입으로 수요 상승 예상" },
  { product_id: "P019", product_name: "손질 오징어 2마리", category: "수산", days_until_expiry: 0, stock_quantity: 9, cost: 5200, regular_price: 8900, recommended_rate: 0.4, expected_loss: 46800, sell_probability: 0.74, esl_applicable: true, reason: "당일 폐기 예정 · 40% 상한 적용 · 마감 시간대 소진율 76%" },
  { product_id: "P036", product_name: "모듬 초밥 12P", category: "즉석", days_until_expiry: 0, stock_quantity: 6, cost: 8400, regular_price: 13900, recommended_rate: 0.4, expected_loss: 50400, sell_probability: 0.69, esl_applicable: false, reason: "즉석식품 당일 소진 필요 · 40% 할인 시 판매확률 69% · ESL 미적용으로 수기 라벨 필요" },
  { product_id: "P008", product_name: "닭가슴살 1kg", category: "축산", days_until_expiry: 1, stock_quantity: 15, cost: 9800, regular_price: 14500, recommended_rate: 0.3, expected_loss: 147000, sell_probability: 0.66, esl_applicable: true, reason: "미판매 시 손실 14.7만원 · 30% 할인 시 판매확률 66%" },
  { product_id: "P027", product_name: "우유 1L", category: "유제품", days_until_expiry: 2, stock_quantity: 24, cost: 2100, regular_price: 3130, recommended_rate: 0.2, expected_loss: 50400, sell_probability: 0.88, esl_applicable: true, reason: "유통기한-가치 연동 품목으로 조기 할인 효과 큼 · 20% 할인 시 소진율 88%" },
  { product_id: "P031", product_name: "플레인 요거트 4입", category: "유제품", days_until_expiry: 2, stock_quantity: 18, cost: 2600, regular_price: 3980, recommended_rate: 0.2, expected_loss: 46800, sell_probability: 0.81, esl_applicable: true, reason: "20% 할인 시 소진율 81% · 잔여 2일로 조기 조치 권장" },
  { product_id: "P042", product_name: "손질 대파 300g", category: "청과", days_until_expiry: 0, stock_quantity: 22, cost: 1500, regular_price: 2450, recommended_rate: 0.4, expected_loss: 33000, sell_probability: 0.83, esl_applicable: true, reason: "당일 폐기 예정 · 회전 빠른 품목으로 40% 할인 시 대부분 소진" },
  { product_id: "P011", product_name: "국내산 사과 5입", category: "청과", days_until_expiry: 2, stock_quantity: 14, cost: 8900, regular_price: 12400, recommended_rate: 0.2, expected_loss: 124600, sell_probability: 0.72, esl_applicable: true, reason: "주말 수요 상승 구간 · 20% 할인으로 충분한 소진 예상" },
  { product_id: "P022", product_name: "모둠 쌈채소", category: "청과", days_until_expiry: 1, stock_quantity: 11, cost: 2200, regular_price: 3500, recommended_rate: 0.3, expected_loss: 24200, sell_probability: 0.77, esl_applicable: true, reason: "잔여 1일 · 30% 할인 시 판매확률 77%" },
];

const STORE_FACTOR = { S01: 1, S02: 0.86, S03: 0.78, S04: 0.92 };

function mockRecs(storeId) {
  const f = STORE_FACTOR[storeId] ?? 1;
  return BASE_RECS.map((r) => ({
    ...r,
    stock_quantity: Math.max(1, Math.round(r.stock_quantity * f)),
    expected_loss: Math.round(r.expected_loss * f),
  }));
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

const MOCK_INVENTORY = [
  { product_id: "P001", product_name: "한우 등심 300g", category: "축산", stock_quantity: 8, days_until_expiry: 0, turnover: 0.42, cost: 38000, regular_price: 52000, sell_probability: 0.78, esl_applicable: true, recommended_rate: 0.4, expected_loss: 304000, reason: "당일 폐기 예정 · 40% 상한 적용" },
  { product_id: "P002", product_name: "한우 채끝 300g", category: "축산", stock_quantity: 14, days_until_expiry: 3, turnover: 0.61, cost: 34000, regular_price: 46000, sell_probability: 0.7, esl_applicable: true, recommended_rate: 0, expected_loss: 0, reason: "잔여 3일 · 현재 조치 불필요" },
  { product_id: "P008", product_name: "닭가슴살 1kg", category: "축산", stock_quantity: 15, days_until_expiry: 1, turnover: 0.55, cost: 9800, regular_price: 14500, sell_probability: 0.66, esl_applicable: true, recommended_rate: 0.3, expected_loss: 147000, reason: "잔여 1일 · 30% 권장" },
  { product_id: "P014", product_name: "삼겹살 500g", category: "축산", stock_quantity: 12, days_until_expiry: 1, turnover: 0.72, cost: 13100, regular_price: 18650, sell_probability: 0.71, esl_applicable: true, recommended_rate: 0.3, expected_loss: 157200, reason: "잔여 1일 · 주말 수요 상승" },
  { product_id: "P019", product_name: "손질 오징어 2마리", category: "수산", stock_quantity: 9, days_until_expiry: 0, turnover: 0.38, cost: 5200, regular_price: 8900, sell_probability: 0.74, esl_applicable: true, recommended_rate: 0.4, expected_loss: 46800, reason: "당일 폐기 예정" },
  { product_id: "P020", product_name: "고등어 2마리", category: "수산", stock_quantity: 16, days_until_expiry: 2, turnover: 0.58, cost: 3900, regular_price: 6200, sell_probability: 0.7, esl_applicable: true, recommended_rate: 0, expected_loss: 0, reason: "잔여 2일 · 회전 정상" },
  { product_id: "P011", product_name: "국내산 사과 5입", category: "청과", stock_quantity: 14, days_until_expiry: 2, turnover: 0.66, cost: 8900, regular_price: 12400, sell_probability: 0.72, esl_applicable: true, recommended_rate: 0.2, expected_loss: 124600, reason: "주말 수요 상승 구간" },
  { product_id: "P022", product_name: "모둠 쌈채소", category: "청과", stock_quantity: 11, days_until_expiry: 1, turnover: 0.7, cost: 2200, regular_price: 3500, sell_probability: 0.77, esl_applicable: true, recommended_rate: 0.3, expected_loss: 24200, reason: "잔여 1일" },
  { product_id: "P042", product_name: "손질 대파 300g", category: "청과", stock_quantity: 22, days_until_expiry: 0, turnover: 0.81, cost: 1500, regular_price: 2450, sell_probability: 0.83, esl_applicable: true, recommended_rate: 0.4, expected_loss: 33000, reason: "당일 폐기 예정 · 회전 빠름" },
  { product_id: "P027", product_name: "우유 1L", category: "유제품", stock_quantity: 24, days_until_expiry: 2, turnover: 0.88, cost: 2100, regular_price: 3130, sell_probability: 0.88, esl_applicable: true, recommended_rate: 0.2, expected_loss: 50400, reason: "유통기한-가치 연동 품목" },
  { product_id: "P031", product_name: "플레인 요거트 4입", category: "유제품", stock_quantity: 18, days_until_expiry: 2, turnover: 0.74, cost: 2600, regular_price: 3980, sell_probability: 0.81, esl_applicable: true, recommended_rate: 0.2, expected_loss: 46800, reason: "조기 조치 권장" },
  { product_id: "P036", product_name: "모듬 초밥 12P", category: "즉석", stock_quantity: 6, days_until_expiry: 0, turnover: 0.69, cost: 8400, regular_price: 13900, sell_probability: 0.69, esl_applicable: false, recommended_rate: 0.4, expected_loss: 50400, reason: "당일 소진 필요 · 수기 라벨" },
  { product_id: "P037", product_name: "김밥 2줄", category: "즉석", stock_quantity: 10, days_until_expiry: 0, turnover: 0.79, cost: 3200, regular_price: 5500, sell_probability: 0.75, esl_applicable: false, recommended_rate: 0.4, expected_loss: 32000, reason: "당일 소진 필요 · 수기 라벨" },
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
  const res = await fetch(BASE + path, { headers: { "Content-Type": "application/json" }, ...options });
  if (!res.ok) throw new Error(`API ${res.status}`);
  return res.json();
}

export async function login(id, pw, storeId) {
  if (USE_MOCK) {
    await delay(650);
    if (!id || !pw) throw new Error("아이디와 비밀번호를 입력해주세요.");
    if (pw.length < 4) throw new Error("비밀번호가 올바르지 않습니다.");
    return { user: { id, name: "임종욱", role: "신선1부문 관리자" }, stores: STORES, storeId: storeId ?? "S01" };
  }
  return call("/login", { method: "POST", body: JSON.stringify({ id, pw, store_id: storeId }) });
}
export async function getStores() {
  if (USE_MOCK) { await delay(150); return STORES; }
  return call("/stores");
}
export async function getSummary(storeId) {
  if (USE_MOCK) { await delay(600); return mockSummary(storeId); }
  return call(`/summary?store_id=${storeId}`);
}
export async function getRecommendations(storeId) {
  if (USE_MOCK) { await delay(700); return mockRecs(storeId); }
  return call(`/recommendations?store_id=${storeId}`);
}
export async function getInventory(storeId) {
  if (USE_MOCK) { await delay(600); return MOCK_INVENTORY; }
  return call(`/inventory?store_id=${storeId}`);
}
export async function approve(storeId, items) {
  if (USE_MOCK) {
    await delay(900);
    return { approved: items.length, esl_sent: Math.max(items.length - 1, 0), esl_failed: items.length ? 1 : 0 };
  }
  return call("/approve", { method: "POST", body: JSON.stringify({ store_id: storeId, items }) });
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
const MOCK_HISTORY = [
  { id: "H231", date: "2026-07-20 08:34", user: "임종욱", product_name: "한우 등심 300g", category: "축산", recommended_rate: 0.4, approved_rate: 0.4, result: "sold", sold_qty: 7, stock_quantity: 8, revenue: 218400 },
  { id: "H230", date: "2026-07-20 08:34", user: "임종욱", product_name: "삼겹살 500g", category: "축산", recommended_rate: 0.3, approved_rate: 0.25, result: "partial", sold_qty: 7, stock_quantity: 12, revenue: 97800 },
  { id: "H229", date: "2026-07-20 08:34", user: "임종욱", product_name: "우유 1L", category: "유제품", recommended_rate: 0.2, approved_rate: 0.2, result: "sold", sold_qty: 22, stock_quantity: 24, revenue: 55100 },
  { id: "H228", date: "2026-07-19 19:02", user: "박신선", product_name: "손질 오징어 2마리", category: "수산", recommended_rate: 0.4, approved_rate: 0.4, result: "sold", sold_qty: 8, stock_quantity: 9, revenue: 42700 },
  { id: "H227", date: "2026-07-19 19:02", user: "박신선", product_name: "모듬 초밥 12P", category: "즉석", recommended_rate: 0.4, approved_rate: 0.3, result: "wasted", sold_qty: 3, stock_quantity: 6, revenue: 29190 },
  { id: "H226", date: "2026-07-19 08:31", user: "임종욱", product_name: "국내산 사과 5입", category: "청과", recommended_rate: 0.2, approved_rate: 0.2, result: "sold", sold_qty: 11, stock_quantity: 14, revenue: 109120 },
  { id: "H225", date: "2026-07-19 08:31", user: "임종욱", product_name: "닭가슴살 1kg", category: "축산", recommended_rate: 0.3, approved_rate: 0.25, result: "wasted", sold_qty: 6, stock_quantity: 15, revenue: 65250 },
  { id: "H224", date: "2026-07-18 19:14", user: "박신선", product_name: "모둠 쌈채소", category: "청과", recommended_rate: 0.3, approved_rate: 0.3, result: "sold", sold_qty: 10, stock_quantity: 11, revenue: 24500 },
  { id: "H223", date: "2026-07-18 08:29", user: "임종욱", product_name: "플레인 요거트 4입", category: "유제품", recommended_rate: 0.2, approved_rate: 0.15, result: "partial", sold_qty: 12, stock_quantity: 18, revenue: 40596 },
  { id: "H222", date: "2026-07-18 08:29", user: "임종욱", product_name: "고등어 2마리", category: "수산", recommended_rate: 0.3, approved_rate: 0.3, result: "sold", sold_qty: 14, stock_quantity: 16, revenue: 60760 },
];

export async function getHistory(storeId) {
  if (USE_MOCK) { await delay(600); return MOCK_HISTORY; }
  return call(`/history?store_id=${storeId}`);
}

/* ---------- 본사 뷰 ---------- */
const MOCK_HQ = {
  total_saved: 41200000, total_stores: 4, avg_waste_rate: 0.034, adoption_rate: 0.89,
  stores: [
    { store_id: "S01", name: "롯데마트 서울역점", area: "복합", waste_rate: 0.031, saved: 12400000, approval_rate: 0.91, pending: 10, trend: -1.8 },
    { store_id: "S02", name: "롯데마트 양평점", area: "주거", waste_rate: 0.029, saved: 10800000, approval_rate: 0.94, pending: 9, trend: -2.1 },
    { store_id: "S03", name: "롯데마트 잠실점", area: "오피스", waste_rate: 0.042, saved: 9100000, approval_rate: 0.82, pending: 8, trend: -0.9 },
    { store_id: "S04", name: "롯데마트 청량리점", area: "주거", waste_rate: 0.035, saved: 8900000, approval_rate: 0.88, pending: 9, trend: -1.4 },
  ],
  rollout: [
    { phase: "파일럿", stores: 4, status: "done", desc: "수도권 4개점 · 3개월" },
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
/* 2단 결재 임계값: 이 값을 초과하는 할인은 담당자 승인 후 점장 최종 승인이 필요합니다 */
export const APPROVAL_THRESHOLD = 30;

export const DEFAULT_POLICY = {
  max_discount: 40,
  two_step_over: 30,
  step_d2: 20, step_d1: 30, step_d0: 40,
  closing_hour: 20,
  auto_approve_under: 0,
  notify_esl_fail: true,
  notify_new_risk: true,
};

export async function savePolicy(storeId, policy) {
  if (USE_MOCK) { await delay(600); return { ok: true, policy }; }
  return call("/policy", { method: "POST", body: JSON.stringify({ store_id: storeId, ...policy }) });
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
  design: "수도권 4개점 중 2개점 적용(처치군) · 2개점 미적용(대조군) · 상권·매출규모 매칭",
  treatment: { stores: ["서울역점", "양평점"], waste_rate: 0.030, margin_rate: 0.121, conversion: 0.68 },
  control: { stores: ["잠실점", "청량리점"], waste_rate: 0.047, margin_rate: 0.118, conversion: 0.44 },
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
  /* 단순 반응모형: 상한↑ → 소진율↑(수확체감), 마진↓ / 조기시작 → 소진율↑, 마진↓ */
  const base = { wastePerStore: 84.5, wasteCostPerTon: 1470000, marginRate: 0.197 };
  const sellLift = Math.min(0.55, (maxDiscount - 30) * 0.028 + (startDay - 1) * 0.06);
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
  if (USE_MOCK) {
    await delay(450);
    return [
      { product_id: "P002", product_name: "한우 채끝 300g", category: "축산", reason: "잔여 3일 · 예상 소진율 92%로 조치 불필요", type: "ok" },
      { product_id: "P020", product_name: "고등어 2마리", category: "수산", reason: "잔여 2일 · 회전율 정상 범위", type: "ok" },
      { product_id: "P055", product_name: "즉석 도시락", category: "즉석", reason: "재고 2개 미만 · 할인 효과 대비 관리비용 큼", type: "skip" },
      { product_id: "P061", product_name: "수입 체리 500g", category: "청과", reason: "행사 진행 중 · 중복 할인 방지 규칙 적용", type: "block" },
    ];
  }
  return call(`/recommendations/skipped?store_id=${storeId}`);
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

/* ---------- 할인율별 기대 손익 곡선 ---------- */
const DISPOSAL_FEE_PER_UNIT = 100; // 147원/kg × 평균 중량 근사

export function profitCurve(item) {
  const pRec = item.sell_probability ?? 0.7;
  const pBase = pRec * 0.55;
  const rows = [];
  for (let r = 0; r <= 40; r += 2) {
    const resp = r < 30 ? 0 : (r - 30) / 10;
    const p = Math.min(pBase + (pRec - pBase) * resp, 0.97);
    const price = Math.round((item.regular_price * (1 - r / 100)) / 10) * 10;
    const sold = item.stock_quantity * p;
    const unsold = item.stock_quantity - sold;
    const net = sold * (price - item.cost) - unsold * (item.cost + DISPOSAL_FEE_PER_UNIT);
    rows.push({ rate: r, net: Math.round(net), sold: +sold.toFixed(1), price, prob: +(p * 100).toFixed(0) });
  }
  return rows;
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
