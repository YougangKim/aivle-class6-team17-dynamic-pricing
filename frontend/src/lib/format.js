export const won = (n) => Number(n || 0).toLocaleString("ko-KR");
export const man = (n) => (Number(n || 0) / 10000).toFixed(1);
export const pct = (n) => Math.round(Number(n || 0) * 100);
export const discounted = (price, rate) => Math.round((price * (1 - rate)) / 10) * 10;
