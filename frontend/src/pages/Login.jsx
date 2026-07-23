import { useState, useEffect } from "react";
import { Store, Loader2, ArrowRight } from "lucide-react";
import { login, getStores, ROLES } from "../lib/api";
import { BRAND } from "../lib/brand";
import { BrandMark } from "../components/ui";

export default function Login({ onLogin }) {
  const [id, setId] = useState("lim.jw");
  const [pw, setPw] = useState("aivle2026");
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [stores, setStores] = useState([]);
  const [storeId, setStoreId] = useState("S01");
  const [role, setRole] = useState("manager");

  useEffect(() => { getStores().then(setStores).catch(() => {}); }, []);

  const submit = async (e) => {
    e.preventDefault();
    setErr(""); setLoading(true);
    try {
      const res = await login(id, pw, storeId);
      onLogin({ ...res, role });
    } catch (e) {
      setErr(e.message);
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen">
      {/* 좌측 브랜드 */}
      <div className="relative hidden flex-1 flex-col justify-between overflow-hidden bg-slate-900 p-12 lg:flex">
        <div className="absolute -right-24 -top-24 h-96 w-96 rounded-full bg-brand-600 opacity-25 blur-3xl" />
        <div className="absolute -bottom-32 -left-16 h-96 w-96 rounded-full bg-cjblue-600 opacity-20 blur-3xl" />
        <div className="absolute bottom-24 right-10 h-64 w-64 rounded-full bg-cjorange-500 opacity-10 blur-3xl" />
        <div className="relative">
          <div className="flex items-center gap-3">
            <BrandMark size={34} plate />
            <p className="text-2xl font-bold tracking-tight text-white">
              Fresh<span className="text-brand-500">Watch</span>
            </p>
          </div>
          <p className="mt-1.5 text-xs text-slate-500">{BRAND.tagline}</p>
        </div>
        <div className="relative">
          <h1 className="text-4xl font-bold leading-tight tracking-tight text-white">
            버리기 전에<br />
            <span className="text-brand-500">파는 가격</span>을 알려드립니다
          </h1>
          <p className="mt-5 max-w-md text-sm leading-relaxed text-slate-400">
            AI가 재고·유통기한·수요를 분석해 순이익이 가장 커지는 할인율을 추천하고,
            담당자가 승인하면 ESL에 즉시 반영됩니다.
          </p>
          <div className="mt-10 flex gap-10">
            {[["폐기율", "4.9% → 2.1%"], ["가격 조정", "32분 → 6분"], ["월 절감", "612만원"]].map(([k, v]) => (
              <div key={k}>
                <p className="text-xs text-slate-500">{k}</p>
                <p className="mt-1 text-lg font-bold text-white">{v}</p>
              </div>
            ))}
          </div>
        </div>
        <div className="relative flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
          <span className="rounded-full bg-slate-800 px-3 py-1 font-semibold text-slate-300">
            {BRAND.vendorRole} {BRAND.vendor}
          </span>
          <span className="rounded-full bg-slate-800 px-3 py-1 font-semibold text-slate-300">
            {BRAND.clientRole} {BRAND.client}
          </span>
          <span className="text-slate-600">{BRAND.project}</span>
        </div>
      </div>

      {/* 우측 폼 */}
      <div className="flex flex-1 items-center justify-center bg-white px-6">
        <form onSubmit={submit} className="w-full max-w-sm">
          <p className="flex items-center gap-2 text-2xl font-bold tracking-tight lg:hidden">
            <BrandMark size={28} />Fresh<span className="text-brand-600">Watch</span>
          </p>
          <h2 className="mt-2 text-xl font-bold tracking-tight lg:mt-0">로그인</h2>
          <p className="mt-1 text-sm text-slate-500">{BRAND.client} 점포 담당자 계정으로 접속해주세요.</p>

          <label className="mt-8 block text-xs font-semibold text-slate-600">매장</label>
          <select
            value={storeId}
            onChange={(e) => setStoreId(e.target.value)}
            className="mt-1.5 w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm outline-none transition-colors focus:border-brand-500 focus:ring-4 focus:ring-brand-50"
          >
            {stores.map((s) => (
              <option key={s.store_id} value={s.store_id}>{s.name}</option>
            ))}
          </select>

          <label className="mt-4 block text-xs font-semibold text-slate-600">권한</label>
          <div className="mt-1.5 grid grid-cols-3 gap-1.5">
            {Object.values(ROLES).map((r) => (
              <button key={r.key} type="button" onClick={() => setRole(r.key)}
                      className={`rounded-xl border px-2 py-2.5 text-[11px] font-semibold transition-all ${
                        role === r.key ? "border-brand-500 bg-brand-50 text-brand-700" : "border-slate-200 text-slate-500 hover:border-slate-300"
                      }`}>
                {r.label}
              </button>
            ))}
          </div>

          <label className="mt-4 block text-xs font-semibold text-slate-600">사번 / 아이디</label>
          <input
            value={id}
            onChange={(e) => setId(e.target.value)}
            className="mt-1.5 w-full rounded-xl border border-slate-200 px-4 py-3 text-sm outline-none transition-colors focus:border-brand-500 focus:ring-4 focus:ring-brand-50"
            placeholder="kim.fresh"
          />

          <label className="mt-4 block text-xs font-semibold text-slate-600">비밀번호</label>
          <input
            type="password"
            value={pw}
            onChange={(e) => setPw(e.target.value)}
            className="mt-1.5 w-full rounded-xl border border-slate-200 px-4 py-3 text-sm outline-none transition-colors focus:border-brand-500 focus:ring-4 focus:ring-brand-50"
            placeholder="••••••••"
          />

          {err && <p className="mt-3 rounded-lg bg-brand-50 px-3 py-2 text-xs text-brand-700">{err}</p>}

          <button
            type="submit"
            disabled={loading}
            className="mt-6 flex w-full items-center justify-center gap-2 rounded-xl bg-brand-600 py-3.5 text-sm font-semibold text-white shadow-sm transition-all hover:bg-brand-700 hover:shadow active:scale-95 disabled:opacity-60"
          >
            {loading ? <Loader2 size={16} className="animate-spin" /> : <ArrowRight size={16} />}
            {loading ? "접속 중" : "로그인"}
          </button>

          <div className="mt-6 flex items-center gap-2 rounded-xl bg-slate-50 px-3 py-2.5 text-xs text-slate-500">
            <Store size={14} className="shrink-0" />
            데모 계정이 입력되어 있습니다. 그대로 로그인하세요.
          </div>
          <p className="mt-4 text-center text-[11px] text-slate-400">
            Powered by {BRAND.vendor}
          </p>
        </form>
      </div>
    </div>
  );
}
