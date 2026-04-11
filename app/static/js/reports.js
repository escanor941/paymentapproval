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

async function loadAllReport() {
  const out = document.getElementById('reportOutput');
  const res = await fetch(`/reports/all?${reportFilters().toString()}`);
  const data = await res.json();
  out.textContent = JSON.stringify(data, null, 2);
}
window.loadAllReport = loadAllReport;

async function quickReport(name) {
  const out = document.getElementById('reportOutput');
  const res = await fetch(`/reports/${name}`);
  const data = await res.json();
  out.textContent = JSON.stringify(data, null, 2);
}
window.quickReport = quickReport;

function exportReport(format) {
  const params = reportFilters();
  params.set('format', format);
  window.open(`/reports/export?${params.toString()}`, '_blank');
}
window.exportReport = exportReport;

loadAllReport();
