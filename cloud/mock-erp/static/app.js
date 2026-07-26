const rows = document.querySelector('#inventoryRows');
const summary = document.querySelector('#summary');
const statusFilter = document.querySelector('#statusFilter');
const recordDialog = document.querySelector('#recordDialog');
const previewDialog = document.querySelector('#previewDialog');
const form = document.querySelector('#recordForm');
const formFields = document.querySelector('#formFields');
const formError = document.querySelector('#formError');

const fields = [
  ['inventory_id','재고 ID','text','INV000004'], ['store_id','매장 ID','text','STORE001'],
  ['product_id','상품 ID','text','PROD004'], ['lot_id','로트 ID','text','LOT20260722001'],
  ['current_date','기준일자','date','2026-07-22'], ['manufacture_date','제조일','date','2026-07-20'],
  ['expiry_date','소비기한','date','2026-07-27'], ['inbound_qty','입고수량','number','50'],
  ['daily_sold_qty','당일 판매수량','number','0'], ['daily_waste_qty','당일 폐기수량','number','0'],
  ['current_stock_qty','현재 재고수량','number','50'], ['reserved_qty','예약수량','number','0'],
  ['unit_cost','원가','number','3500'], ['unit_price','정상 판매가','number','4980'],
  ['discount_rate','할인율(%)','number','0'], ['weight_kg','중량(kg)','number','0.45'],
  ['inventory_status','재고 상태','select','ON_SALE'], ['waste_reason','폐기 사유','text','']
];

formFields.innerHTML = fields.map(([name,label,type,value]) => {
  if (type === 'select') return `<label>${label}<select name="${name}"><option>ON_SALE</option><option>OUT_OF_STOCK</option><option>DISPOSAL</option><option>RESERVED</option></select></label>`;
  const step = name === 'weight_kg' ? ' step="0.01"' : '';
  const required = name === 'waste_reason' ? '' : ' required';
  return `<label>${label}<input name="${name}" type="${type}" value="${value}"${step}${required}></label>`;
}).join('');

function money(value){ return new Intl.NumberFormat('ko-KR').format(value) + '원'; }
function statusPill(item){
  const cls = item.inventory_status === 'DISPOSAL' ? 'danger' : item.days_to_expiry <= 1 ? 'warn' : '';
  return `<span class="pill ${cls}">${item.inventory_status}</span>`;
}

async function loadInventory(){
  const query = statusFilter.value ? `?inventory_status=${statusFilter.value}` : '';
  const response = await fetch(`/api/inventory${query}`);
  const data = await response.json();
  rows.innerHTML = data.items.map(item => `<tr>
    <td>${item.inventory_id}</td><td>${item.store_id}</td><td>${item.product_id}</td><td>${item.lot_id}</td>
    <td>${item.expiry_date}</td><td>${item.days_to_expiry}</td><td>${item.available_qty}</td>
    <td>${item.freshness_score.toFixed(1)}</td><td>${money(item.discount_price)}</td><td>${statusPill(item)}</td>
  </tr>`).join('') || '<tr><td colspan="10">조건에 맞는 재고가 없습니다.</td></tr>';
  const totalStock = data.items.reduce((sum,item) => sum + item.current_stock_qty, 0);
  const available = data.items.reduce((sum,item) => sum + item.available_qty, 0);
  const disposal = data.items.filter(item => item.disposal_candidate === 'Y').length;
  summary.innerHTML = [
    ['조회 재고', `${data.count}건`], ['현재 재고', `${totalStock}개`],
    ['판매 가능', `${available}개`], ['폐기 후보', `${disposal}건`]
  ].map(([label,value]) => `<div class="card"><span>${label}</span><strong>${value}</strong></div>`).join('');
}

statusFilter.addEventListener('change', loadInventory);
document.querySelector('#newButton').addEventListener('click', () => recordDialog.showModal());
document.querySelector('#closeDialog').addEventListener('click', () => recordDialog.close());
document.querySelector('#cancelDialog').addEventListener('click', () => recordDialog.close());
document.querySelector('#closePreview').addEventListener('click', () => previewDialog.close());
document.querySelector('#previewButton').addEventListener('click', async () => {
  const response = await fetch('/api/aws/payload-preview?limit=10');
  document.querySelector('#payloadPreview').textContent = JSON.stringify(await response.json(), null, 2);
  previewDialog.showModal();
});

form.addEventListener('submit', async event => {
  event.preventDefault(); formError.textContent = '';
  const data = Object.fromEntries(new FormData(form).entries());
  ['inbound_qty','daily_sold_qty','daily_waste_qty','current_stock_qty','reserved_qty','unit_cost','unit_price','discount_rate'].forEach(key => data[key] = Number(data[key]));
  data.weight_kg = Number(data.weight_kg);
  if (!data.waste_reason) data.waste_reason = null;
  const response = await fetch('/api/inventory', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)});
  if (!response.ok){ const error = await response.json(); formError.textContent = JSON.stringify(error.detail, null, 2); return; }
  recordDialog.close(); await loadInventory();
});

loadInventory();

