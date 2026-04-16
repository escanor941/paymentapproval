const reqBody = document.querySelector('#reqTable tbody');
const simpleBillBody = document.querySelector('#billUploadTable tbody');
let prevUnread = 0;
let requestFilterActive = false;
const ADMIN_REQ_CACHE_KEY = 'admin_requests_cache_v1';
const ADMIN_FILTER_CACHE_KEY = 'admin_request_filters_v1';

function getFilterValues() {
  return {
    fFrom: document.getElementById('fFrom')?.value || '',
    fTo: document.getElementById('fTo')?.value || '',
    fFactory: document.getElementById('fFactory')?.value || '',
    fVendor: document.getElementById('fVendor')?.value || '',
    fStatus: document.getElementById('fStatus')?.value || '',
    fPayment: document.getElementById('fPayment')?.value || '',
  };
}

function applySavedFilters() {
  try {
    const raw = localStorage.getItem(ADMIN_FILTER_CACHE_KEY);
    if (!raw) return;
    const saved = JSON.parse(raw);
    ['fFrom', 'fTo', 'fFactory', 'fVendor', 'fStatus', 'fPayment'].forEach((id) => {
      const el = document.getElementById(id);
      if (el && typeof saved[id] === 'string') el.value = saved[id];
    });
    requestFilterActive = Boolean(saved.requestFilterActive);
  } catch {
    // Ignore corrupt browser cache and continue with defaults.
  }
}

function saveFilterState() {
  try {
    localStorage.setItem(
      ADMIN_FILTER_CACHE_KEY,
      JSON.stringify({ requestFilterActive, ...getFilterValues() })
    );
  } catch {
    // Ignore browser storage errors.
  }
}

function factoryNameFromId(id) {
  const sel = document.getElementById('fFactory');
  if (!sel) return String(id ?? '');
  const opt = Array.from(sel.options).find((x) => x.value === String(id));
  return opt?.textContent || String(id ?? '');
}

function cacheRequests(items) {
  try {
    localStorage.setItem(
      ADMIN_REQ_CACHE_KEY,
      JSON.stringify({
        savedAt: new Date().toISOString(),
        items,
      })
    );
  } catch {
    // Ignore browser storage errors.
  }
}

function renderRequests(items) {
  reqBody.innerHTML = '';
  (items || []).forEach(it => {
    const tr = document.createElement('tr');
    if (it.is_unread_admin) tr.classList.add('new-row');
    tr.innerHTML = `
      <td>${it.id}</td>
      <td>${it.request_date}</td>
      <td>${factoryNameFromId(it.factory_id)}</td>
      <td>${it.vendor || ''}</td>
      <td>${it.item_name}</td>
      <td>${it.qty} ${it.unit}</td>
      <td>${Number(it.final_amount).toFixed(2)}</td>
      <td>${it.requested_by}</td>
      <td>${b(it.approval_status)}</td>
      <td>${b(it.payment_status)}</td>
      <td class="d-flex flex-wrap gap-1">
        <button class="btn btn-sm btn-outline-dark" onclick="viewDetails(${it.id})">View</button>
        ${it.bill_image_path ? `<a target="_blank" class="btn btn-sm btn-outline-secondary" href="${it.bill_image_path}">Bill</a>` : ''}
        <button class="btn btn-sm btn-outline-primary" onclick="editRequest(${it.id})">Edit</button>
        <button class="btn btn-sm btn-success" onclick="openApprove(${it.id})">Approve</button>
        <button class="btn btn-sm btn-danger" onclick="openReject(${it.id})">Reject</button>
        <button class="btn btn-sm btn-warning" onclick="holdRequest(${it.id})">Hold</button>
        <button class="btn btn-sm btn-primary" onclick="openPay(${it.id})">Mark Paid</button>
        <button class="btn btn-sm btn-outline-danger" onclick="deleteRequest(${it.id})">Delete</button>
        <button class="btn btn-sm btn-outline-dark" onclick="window.print()">Print</button>
      </td>
    `;
    reqBody.appendChild(tr);
  });
}

function restoreRequestsFromCache() {
  if (!reqBody) return;
  try {
    const raw = localStorage.getItem(ADMIN_REQ_CACHE_KEY);
    if (!raw) return;
    const saved = JSON.parse(raw);
    if (Array.isArray(saved.items) && saved.items.length) {
      renderRequests(saved.items);
    }
  } catch {
    // Ignore corrupt browser cache and continue with live data fetch.
  }
}

function b(status) {
  if (status === 'Pending') return '<span class="badge badge-pending">Pending</span>';
  if (status === 'Approved') return '<span class="badge badge-approved">Approved</span>';
  if (status === 'Rejected') return '<span class="badge badge-rejected">Rejected</span>';
  if (status === 'Paid') return '<span class="badge badge-paid">Paid</span>';
  return `<span class="badge text-bg-secondary">${status}</span>`;
}

async function loadRequests() {
  if (!reqBody) return;
  const params = new URLSearchParams();
  if (requestFilterActive) {
    const map = [
      ['from_date', 'fFrom'],
      ['to_date', 'fTo'],
      ['factory_id', 'fFactory'],
      ['vendor', 'fVendor'],
      ['status', 'fStatus'],
      ['payment_status', 'fPayment'],
    ];
    map.forEach(([k, id]) => {
      const val = document.getElementById(id)?.value;
      if (val) params.set(k, val);
    });
  }

  saveFilterState();
  const res = await fetch(`/requests?${params.toString()}`);
  const data = await res.json();
  renderRequests(data.items || []);
  cacheRequests(data.items || []);
}
window.loadRequests = loadRequests;

function applyRequestFilters() {
  requestFilterActive = true;
  saveFilterState();
  loadRequests();
}
window.applyRequestFilters = applyRequestFilters;

async function loadSimpleBills() {
  if (!simpleBillBody) return;
  const res = await fetch('/requests?item_category=Bill Upload');
  const data = await res.json();
  simpleBillBody.innerHTML = '';

  (data.items || []).forEach(it => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${it.id}</td>
      <td>${it.request_date}</td>
      <td>${it.vendor || ''}</td>
      <td>${it.requested_by || ''}</td>
      <td>${b(it.approval_status)}</td>
      <td>${it.bill_image_path ? `<a target="_blank" class="btn btn-sm btn-outline-secondary" href="${it.bill_image_path}">View Bill</a>` : '<span class="text-muted">No file</span>'}</td>
    `;
    simpleBillBody.appendChild(tr);
  });
}
window.loadSimpleBills = loadSimpleBills;

function clearFilters() {
  ['fFrom', 'fTo', 'fFactory', 'fVendor', 'fStatus', 'fPayment'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = '';
  });
  requestFilterActive = false;
  saveFilterState();
  loadRequests();
}
window.clearFilters = clearFilters;

function openApprove(id) {
  document.getElementById('approveRequestId').value = id;
  new bootstrap.Modal('#approveModal').show();
}
window.openApprove = openApprove;

function openReject(id) {
  document.getElementById('rejectRequestId').value = id;
  new bootstrap.Modal('#rejectModal').show();
}
window.openReject = openReject;

function openPay(id) {
  document.getElementById('payRequestId').value = id;
  document.querySelector('#payForm [name="payment_date"]').value = new Date().toISOString().slice(0, 10);
  new bootstrap.Modal('#payModal').show();
}
window.openPay = openPay;

async function holdRequest(id) {
  const remarks = prompt('Hold remarks (optional):') || '';
  const fd = new FormData();
  fd.append('remarks', remarks);
  const res = await fetch(`/requests/${id}/hold`, { method: 'POST', body: fd });
  const data = await res.json();
  alert(data.message || 'Updated');
  loadRequests();
}
window.holdRequest = holdRequest;

async function deleteRequest(id) {
  if (!confirm('Delete request?')) return;
  const res = await fetch(`/requests/${id}`, { method: 'DELETE' });
  const data = await res.json();
  alert(data.message || 'Deleted');
  loadRequests();
}
window.deleteRequest = deleteRequest;

async function editRequest(id) {
  const listRes = await fetch('/requests');
  const listData = await listRes.json();
  const item = (listData.items || []).find(x => x.id === id);
  if (!item) return;

  const itemName = prompt('Item Name:', item.item_name);
  if (itemName === null) return;
  const qty = prompt('Quantity:', item.qty);
  if (qty === null) return;
  const rate = prompt('Rate:', item.rate);
  if (rate === null) return;
  const gst = prompt('GST %:', item.gst_percent || 0);
  if (gst === null) return;
  const reason = prompt('Reason:', item.reason);
  if (reason === null) return;

  const amount = Number(qty) * Number(rate);
  const finalAmount = amount + (amount * Number(gst) / 100);

  const fd = new FormData();
  fd.set('request_date', item.request_date);
  fd.set('factory_id', item.factory_id);
  fd.set('vendor_id', item.vendor_id);
  fd.set('vendor_mobile', item.vendor_mobile || '');
  fd.set('item_category', item.item_category);
  fd.set('item_name', itemName);
  fd.set('qty', String(qty));
  fd.set('unit', item.unit);
  fd.set('rate', String(rate));
  fd.set('amount', amount.toFixed(2));
  fd.set('gst_percent', String(gst));
  fd.set('final_amount', finalAmount.toFixed(2));
  fd.set('reason', reason);
  fd.set('urgent_flag', item.urgent_flag ? 'true' : 'false');
  fd.set('requested_by', item.requested_by);
  fd.set('notes', item.notes || '');

  const res = await fetch(`/requests/${id}`, { method: 'PUT', body: fd });
  const data = await res.json();
  alert(data.message || data.detail || 'Updated');
  loadRequests();
}
window.editRequest = editRequest;

async function viewDetails(id) {
  const listRes = await fetch('/requests');
  const listData = await listRes.json();
  const item = (listData.items || []).find(x => x.id === Number(id));
  if (!item) return;
  alert(JSON.stringify(item, null, 2));
}
window.viewDetails = viewDetails;

document.getElementById('approveForm')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  const form = e.target;
  const id = form.request_id.value;
  const fd = new FormData(form);
  const res = await fetch(`/requests/${id}/approve`, { method: 'POST', body: fd });
  const data = await res.json();
  alert(data.message || 'Approved');
  bootstrap.Modal.getInstance(document.getElementById('approveModal'))?.hide();
  loadRequests();
});

document.getElementById('rejectForm')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  const form = e.target;
  const id = form.request_id.value;
  const fd = new FormData(form);
  const res = await fetch(`/requests/${id}/reject`, { method: 'POST', body: fd });
  const data = await res.json();
  alert(data.message || 'Rejected');
  bootstrap.Modal.getInstance(document.getElementById('rejectModal'))?.hide();
  loadRequests();
});

document.getElementById('payForm')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  const form = e.target;
  const id = form.request_id.value;
  const fd = new FormData(form);
  fd.set('partial_payment', form.partial_payment.checked ? 'true' : 'false');
  const res = await fetch(`/requests/${id}/pay`, { method: 'POST', body: fd });
  const data = await res.json();
  if (!res.ok) {
    alert(data.detail || 'Cannot complete payment');
    return;
  }
  alert(`${data.message} | Balance: ${data.balance}`);
  bootstrap.Modal.getInstance(document.getElementById('payModal'))?.hide();
  loadRequests();
});

async function pollNotifications() {
  const badge = document.getElementById('notifBadge');
  const sound = document.getElementById('notifSound');
  if (!badge) return;
  const res = await fetch('/notifications/unread-count');
  if (!res.ok) return;
  const data = await res.json();
  badge.textContent = data.count;
  if (data.count > prevUnread && prevUnread !== 0) {
    sound?.play().catch(() => {});
  }
  prevUnread = data.count;
}

const notifBtn = document.getElementById('notifBtn');
notifBtn?.addEventListener('click', async () => {
  await fetch('/notifications/mark-read', { method: 'POST' });
  pollNotifications();
  loadRequests();
});

setInterval(pollNotifications, 8000);
setInterval(() => {
  if (!document.hidden) {
    loadRequests();
    loadSimpleBills();
  }
}, 12000);

applySavedFilters();
restoreRequestsFromCache();
pollNotifications();
loadRequests();
loadSimpleBills();
