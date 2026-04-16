function reportFilters() {
  const params = new URLSearchParams();
  const map = [
    ['from_date', 'rFrom'],
    ['to_date', 'rTo'],
    ['vendor_id', 'rVendor'],
    ['factory_id', 'rFactory'],
    ['status', 'rStatus'],
    ['payment_status', 'rPayment'],
  ];
  map.forEach(([k, id]) => {
    const v = document.getElementById(id)?.value;
    if (v) params.set(k, v);
  });
  return params;
}

function fmtAmount(v) {
  const n = Number(v || 0);
  if (Number.isNaN(n)) return '0.00';
  return n.toFixed(2);
}

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function pickColumns(items) {
  if (!items.length) return [];
  const preferred = [
    'id',
    'request_date',
    'factory',
    'vendor',
    'item_category',
    'item_name',
    'qty',
    'unit',
    'final_amount',
    'requested_by',
    'approval_status',
    'payment_status',
    'count',
    'total',
    'user',
    'payment_mode',
    'item',
  ];
  const keys = Object.keys(items[0]);
  const ordered = preferred.filter(k => keys.includes(k));
  const remaining = keys.filter(k => !ordered.includes(k));
  return [...ordered, ...remaining];
}

function titleCase(s) {
  return s
    .replaceAll('_', ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function updateSummary(data, items) {
  const countEl = document.getElementById('reportCount');
  const totalEl = document.getElementById('reportTotal');
  const fromEl = document.getElementById('reportFrom');
  const toEl = document.getElementById('reportTo');
  if (!countEl || !totalEl || !fromEl || !toEl) return;

  const count = Number(data.count ?? items.length ?? 0);
  const totalFromResponse = Number(data.total ?? 0);
  const totalFromItems = items.reduce((sum, it) => sum + Number(it.final_amount || it.total || 0), 0);
  const total = totalFromResponse || totalFromItems;

  countEl.textContent = String(count);
  totalEl.textContent = fmtAmount(total);
  fromEl.textContent = data.from || data.date || '-';
  toEl.textContent = data.to || data.date || '-';
}

function renderReportTable(data) {
  const head = document.getElementById('reportHead');
  const body = document.getElementById('reportBody');
  const empty = document.getElementById('reportEmpty');
  if (!head || !body || !empty) return;

  const items = Array.isArray(data.items) ? data.items : [];
  updateSummary(data, items);
  body.innerHTML = '';

  if (!items.length) {
    head.innerHTML = '';
    empty.classList.remove('d-none');
    return;
  }

  const columns = pickColumns(items);
  head.innerHTML = `<tr>${columns.map(c => `<th>${titleCase(c)}</th>`).join('')}</tr>`;
  empty.classList.add('d-none');

  items.forEach((it) => {
    const tr = document.createElement('tr');
    tr.innerHTML = columns.map((c) => {
      const val = it[c];
      if (typeof val === 'number') {
        return `<td>${Number.isInteger(val) ? val : fmtAmount(val)}</td>`;
      }
      return `<td>${escapeHtml(val ?? '')}</td>`;
    }).join('');
    body.appendChild(tr);
  });
}

async function loadAllReport() {
  const res = await fetch(`/reports/all?${reportFilters().toString()}`);
  const data = await res.json();
  renderReportTable(data);
}
window.loadAllReport = loadAllReport;

async function quickReport(name) {
  const res = await fetch(`/reports/${name}`);
  const data = await res.json();
  renderReportTable(data);
}
window.quickReport = quickReport;

function clearReportFilters() {
  ['rFrom', 'rTo', 'rVendor', 'rFactory', 'rStatus', 'rPayment'].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.value = '';
  });
  loadAllReport();
}
window.clearReportFilters = clearReportFilters;

function exportReport(format) {
  const params = reportFilters();
  params.set('format', format);
  window.open(`/reports/export?${params.toString()}`, '_blank');
}
window.exportReport = exportReport;

loadAllReport();
