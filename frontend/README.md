<div align="center">

# FreshWatch AI

**신선식품 폐기저감 · AI 다이나믹 프라이싱 관리자 콘솔**

AI가 순이익이 가장 커지는 할인율을 **추천**하고, 담당자가 **승인**하면 ESL에 즉시 반영됩니다.

[**▶ 데모 바로가기**](https://julim0101.github.io/freshwatch/)

KT AIVLE School 9기 빅프로젝트 · 수도권 06반 17조
제안사 CJ올리브네트웍스 · 고객사 롯데마트(가정)

</div>

---

## 문제

롯데마트 한 점포가 1년에 버리는 음식물은 **84.5톤**, 손실로 환산하면 **연 3.86억 원**입니다.
현장 인터뷰에서 확인한 원인은 명확했습니다.

> "발주는 담당자 역량입니다." — 롯데마트 양평점 부점장 (2026.07.09)

폐기는 **발주 시점**과 **할인 시점** 두 곳에서 결정되는데, 두 판단 모두 사람의 감에 의존하고 있습니다.

## 해결

AI는 가격을 결정하지 않습니다. **추천만 하고 최종 판단은 사람이 합니다.**

```
재고 · 유통기한 · 수요예측 · 날씨
        ↓
AI 할인율 추천 (순이익 최대화 · 본사 상한 40% 준수)
        ↓
담당자 승인 → (30% 초과 시 점장 최종 승인)
        ↓
ESL · POS 즉시 반영
```

---

## 주요 기능

### 점포 화면

| 화면 | 설명 |
| --- | --- |
| **폐기위험 대응** | 실시간 컨텍스트(날씨·시간·휴업), KPI 4종, 손실 흐름·소진 예측 차트, AI 승인 대기열, 마감 모드 |
| **재고 모니터링** | 전체 신선 재고 · 검색/정렬/필터 · 상세 팝업 |
| **승인 이력** | 가격 변경 전건 기록 · 카테고리별 조정 패턴 분석 · CSV 다운로드 |
| **성과 리포트** | 폐기율 추이 · AI 모델 성능(MAPE·드리프트) · 미승인 건의 실제 결과 |

### 본사 화면

| 화면 | 설명 |
| --- | --- |
| **본사 대시보드** | 4개 점포 폐기율 랭킹 · 누적 절감 · 확산 로드맵(4→30→110개점) |
| **ESG 리포트** | 폐기 감축의 탄소(tCO₂e) 환산 · 무게 vs 탄소 비중 · 감축목표 진행률 |
| **효과 검증** | 적용·대조 점포 A/B 비교 · 통계적 유의성 · 선행연구 대비 |
| **정책 시뮬레이터** | 할인 정책 변경 시 전사 폐기·이익 영향 분석 |

### 팝업

**손익 시뮬레이션** (할인율별 기대 손익 곡선 + 수요예측) · **ESL 현황** · **현장 PDA**(오프라인 큐잉) · **정책 설정** · **온보딩 투어**

---

## 핵심 설계

### 1. 왜 40%인가 — 손익 곡선으로 증명

할인율별 기대 손익을 계산해 **정점(최적점)** 을 추천합니다.
30% 미만 구간이 평평한 것은 자체 EDA 결과(할인 30% 미만은 구매 행동을 바꾸지 못함)를 반영한 것입니다.

### 2. 2단 결재

| 할인율 | 결재 |
| --- | --- |
| 0 ~ 30% | 담당자 승인 → ESL 즉시 반영 |
| 31 ~ 40% | 담당자 승인 → **점장 최종 승인** → ESL 반영 |

할인율은 1%p 단위로 조정하며, 본사 지침 상한 40%는 시스템이 강제합니다.

### 3. 권한 분리

| 역할 | 점포 화면 | 본사 화면 | 정책 설정 | 30% 초과 승인 |
| --- | --- | --- | --- | --- |
| 신선팀 담당자 | O | X | X | X |
| 점장 | O | X | O | O |
| 본사 운영팀 | O | O | O | O |

---

## 실행

```bash
npm install
npm run dev        # http://localhost:5173
```

로그인 화면에 데모 계정이 입력되어 있습니다. 매장과 권한을 선택해 접속하세요.
백엔드 없이 목 데이터로 전체 화면이 동작합니다.

```bash
npm run build      # dist/ 생성
npm run deploy     # GitHub Pages 배포
```

---

## 기술 구성

| 구분 | 사용 기술 |
| --- | --- |
| 프론트엔드 | React 18 · Vite · Tailwind CSS |
| 차트 | Recharts |
| 아이콘 | lucide-react |
| 데이터 | `src/lib/api.js` 목 데이터 (`USE_MOCK` 플래그로 실서버 전환) |
| 배포 | GitHub Pages (정적 빌드) |

```
src/
├─ App.jsx              레이아웃 · 라우팅 · 승인 상태 관리 · 2단 결재
├─ lib/
│  ├─ api.js            ★ API 레이어 · 목 데이터 · 손익 계산
│  ├─ brand.js          브랜딩 문구·로고
│  └─ format.js         숫자 포맷
├─ components/          ui · DetailModal · EslModal · PdaModal · SettingsModal
└─ pages/               Login · Home · Inventory · History · Performance
                        Hq · Esg · AbTest · PolicySim
```

---

## 백엔드 연결

`src/lib/api.js` 의 `USE_MOCK = false` 로 바꾸면 실제 서버를 호출합니다.
`vite.config.js` 의 proxy 주석을 해제해 백엔드 주소를 지정하세요.

| 메서드 | 경로 | 응답 |
| --- | --- | --- |
| POST | `/api/login` | `{ user, stores }` |
| GET | `/api/summary?store_id=` | KPI · 카테고리별 위험 · 추이 · 컨텍스트 |
| GET | `/api/recommendations?store_id=` | 추천 상품 배열 |
| POST | `/api/approve` | `{ approved, esl_sent, esl_failed }` |
| GET | `/api/inventory?store_id=` | 전체 재고 |
| GET | `/api/history?store_id=` | 승인 이력 |
| GET | `/api/esl/status?store_id=` | ESL 전송 현황 |
| GET | `/api/kpi?store_id=&period=` | 성과 지표 |
| GET | `/api/model/performance` | 모델 성능(MAPE·드리프트) |
| GET | `/api/hq/overview` | 본사 점포 현황 |

```json
{
  "product_id": "P001",
  "product_name": "한우 등심 300g",
  "category": "축산",
  "days_until_expiry": 0,
  "stock_quantity": 8,
  "cost": 38000,
  "regular_price": 52000,
  "recommended_rate": 0.40,
  "expected_loss": 304000,
  "sell_probability": 0.78,
  "esl_applicable": true,
  "reason": "오늘 미판매 시 폐기 손실 30.4만원 · 40% 할인 시 판매확률 78%"
}
```

> 승인 시 `approved_rate` 와 `recommended_rate` 를 **함께** 저장하도록 요청하세요.
> 담당자가 AI 추천을 얼마나 조정하는지 분석하는 학습 데이터가 됩니다.

---

## 브랜딩 변경

| 항목 | 위치 |
| --- | --- |
| 문구(제안사·고객사·버전) | `src/lib/brand.js` |
| 색상 | `tailwind.config.js` 의 `brand` 팔레트 |
| 심볼 | 내장 SVG 사용. `public/파일명.png` 를 넣고 `brand.js` 의 `clientLogo` 에 지정하면 교체 |

---

## 데이터 근거

| 항목 | 출처 |
| --- | --- |
| 할인 30% 미만 무반응 | 자체 EDA (Dunnhumby 거래 데이터) |
| 할인 상한 40% · D-day 차등 | 현직자 인터뷰 (2026.07.09) |
| 의무휴업 전일 수요 +21% | 자체 EDA (M5 이벤트 전일 효과 유추) |
| 폐기 처리단가 147,000원/톤 | 기후에너지환경부고시 제2025-165호 |
| 점포당 연 폐기 84.5톤 | 롯데쇼핑 2024 지속가능경영보고서 |
| 카테고리별 폐기율·탄소계수 | Eriksson et al.(2015) |
| 다이나믹 프라이싱 효과 | Sanders(2024), Marketing Science |
| 고객 분포·구매 패턴 | 통계청 인구총조사·가계동향조사 2024 |
| 상품 가격 | aT 농수축산물 도소매가 · 한국소비자원 참가격 |

---

## 한계

- 표시된 수치는 공개 데이터(M5·Favorita·Dunnhumby)와 합성 데이터 기반 **예시값**입니다.
- ESL 하드웨어 연동은 표준 인터페이스만 구현하고 목 서버로 검증했습니다.
- A/B 실험 결과는 시뮬레이션 값이며 실제 도입 시 재검증이 필요합니다.
- 축소 모형(고객 2,000명 · 상품 40종 · 4개 점포)이라 절대 수치보다 비율·패턴이 유효합니다.

---

<div align="center">

**KT AIVLE School 9기 · 수도권 06반 17조**

</div>
