import { useState, useMemo } from "react";
import { Search, PackageSearch, ArrowUpDown } from "lucide-react";
import { Panel, DayTag, Skeleton, ErrorBox, Empty, useAsync } from "../components/ui";
import DetailModal from "../components/DetailModal";
import { getInventory } from "../lib/api";
import { won, man } from "../lib/format";

const CATS = ["전체", "축산", "수산", "청과", "유제품", "즉석"];

export default function Inventory({ storeId, onToast }) {
  const { data, loading, error, reload } = useAsync(() => getInventory(storeId), [storeId]);
  const [q, setQ] = useState("");
  const [cat, setCat] = useState("전체");
  const [sort, setSort] = useState("risk");
  const [detail, setDetail] = useState(null);
  const [rates, setRates] = useState({});

  const items = data ?? [];
  const rateOf = (i) => rates[i.product_id] ?? Math.round((i.recommended_rate ?? 0) * 100);

  const rows = useMemo(() => {
    let r = items;
    if (cat !== "전체") r = r.filter((i) => i.category === cat);
    if (q.trim()) r = r.filter((i) => i.product_name.includes(q.trim()));
    const by = {
      risk: (a, b) => b.expected_loss - a.expected_loss,
      expiry: (a, b) => a.days_until_expiry - b.days_until_expiry,
      stock: (a, b) => b.stock_quantity - a.stock_quantity,
      turnover: (a, b) => a.turnover - b.turnover,
    }[sort];
    return [...r].sort(by);
  }, [items, cat, q, sort]);

  if (error) return <ErrorBox message={error} onRetry={reload} />;

  const totalStock = items.reduce((s, i) => s + i.stock_quantity, 0);
  const riskItems = items.filter((i) => i.days_until_expiry <= 1).length;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-56">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="상품명 검색"
            className="w-full rounded-xl border border-slate-200 py-2.5 pl-9 pr-3 text-sm outline-none transition-colors focus:border-brand-500 focus:ring-4 focus:ring-brand-50"
          />
        </div>
        <div className="flex flex-wrap gap-1.5">
          {CATS.map((c) => (
            <button key={c} onClick={() => setCat(c)}
                    className={`rounded-full px-3 py-1.5 text-xs font-semibold transition-all ${
                      cat === c ? "bg-slate-900 text-white" : "border border-slate-200 bg-white text-slate-600 hover:border-slate-300"
                    }`}>
              {c}
            </button>
          ))}
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-xs text-slate-500">
          총 <b className="text-slate-900">{items.length}품목</b> · 재고 {totalStock}개 · 임박(D-1 이내){" "}
          <b className="text-brand-600">{riskItems}품목</b>
        </p>
        <div className="flex items-center gap-1.5 text-xs">
          <ArrowUpDown size={13} className="text-slate-400" />
          {[["risk", "위험도순"], ["expiry", "유통기한순"], ["stock", "재고많은순"], ["turnover", "회전느린순"]].map(([k, l]) => (
            <button key={k} onClick={() => setSort(k)}
                    className={`rounded-lg px-2.5 py-1 font-semibold transition-colors ${
                      sort === k ? "bg-slate-100 text-slate-900" : "text-slate-500 hover:text-slate-700"
                    }`}>
              {l}
            </button>
          ))}
        </div>
      </div>

      <Panel padded={false}>
        {loading ? (
          <div className="space-y-3 p-5">{[0, 1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-12 w-full" />)}</div>
        ) : rows.length === 0 ? (
          <Empty icon={PackageSearch} title="조건에 맞는 상품이 없습니다" desc="검색어나 카테고리를 바꿔보세요." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[680px] text-sm">
              <thead>
                <tr className="border-b border-slate-100 text-left text-xs text-slate-400">
                  <th className="px-5 py-3 font-medium">상품</th>
                  <th className="px-3 py-3 font-medium">유통기한</th>
                  <th className="px-3 py-3 text-right font-medium">재고</th>
                  <th className="px-3 py-3 text-right font-medium">회전율</th>
                  <th className="px-3 py-3 text-right font-medium">폐기 위험</th>
                  <th className="px-5 py-3 text-right font-medium">AI 추천</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((i) => (
                  <tr key={i.product_id} onClick={() => setDetail(i)}
                      className="cursor-pointer border-b border-slate-50 transition-colors last:border-0 hover:bg-slate-50">
                    <td className="px-5 py-3.5">
                      <div className="flex items-center gap-2">
                        <span className="font-semibold">{i.product_name}</span>
                        <span className="rounded-md bg-slate-100 px-2 py-0.5 text-[11px] text-slate-500">{i.category}</span>
                      </div>
                      <p className="mt-0.5 text-xs text-slate-400">정가 {won(i.regular_price)}원 · 원가 {won(i.cost)}원</p>
                    </td>
                    <td className="px-3 py-3.5"><DayTag d={Math.min(i.days_until_expiry, 2)} /></td>
                    <td className="px-3 py-3.5 text-right font-medium">{i.stock_quantity}개</td>
                    <td className="px-3 py-3.5 text-right">
                      <span className={i.turnover < 0.5 ? "font-semibold text-cjorange-600" : "text-slate-600"}>
                        {Math.round(i.turnover * 100)}%
                      </span>
                    </td>
                    <td className="px-3 py-3.5 text-right">
                      {i.expected_loss > 0
                        ? <span className="font-semibold text-brand-600">{man(i.expected_loss)}만원</span>
                        : <span className="text-slate-300">—</span>}
                    </td>
                    <td className="px-5 py-3.5 text-right">
                      {i.recommended_rate > 0
                        ? <span className="rounded-lg bg-brand-50 px-2.5 py-1 text-xs font-bold text-brand-600">−{Math.round(i.recommended_rate * 100)}%</span>
                        : <span className="text-xs text-slate-400">조치 불필요</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <p className="text-xs text-slate-400">상품을 클릭하면 수요예측과 손익 시뮬레이션이 열립니다.</p>

      {detail && (
        <DetailModal
          item={detail}
          rate={rateOf(detail)}
          onRate={(v) => setRates({ ...rates, [detail.product_id]: v })}
          onClose={() => setDetail(null)}
          onApprove={() => {
            setDetail(null);
            onToast({ title: "가격 반영 예약됨", desc: `${detail.product_name} · 폐기위험 대응 화면에서 승인하세요` });
          }}
        />
      )}
    </div>
  );
}
