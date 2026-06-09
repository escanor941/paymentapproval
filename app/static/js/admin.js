const reqBody = document.querySelector('#reqTable tbody');
const simpleBillBody = document.querySelector('#billUploadTable tbody');
const presenceBody = document.querySelector('#presenceTable tbody');
let prevUnread = 0;
let requestFilterActive = false;
const ADMIN_REQ_CACHE_KEY = 'admin_requests_cache_v2';
const ADMIN_FILTER_CACHE_KEY = 'admin_request_filters_v2';
let requestsMap = {};

function escHtml(str) {
  return String(str || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function getFilterValues() {
  return {
    fFrom: document.getElementById('fFrom')?.value || '',
    fTo: document.getElementById('fTo')?.value || '',
    fFactory: document.getElementById('fFactory')?.value || '',
    fType: document.getElementById('fType')?.value || '',
    fStatus: document.getElementById('fStatus')?.value || '',
    fPayment: document.getElementById('fPayment')?.value || '',
    fCompletion: document.getElementById('fCompletion')?.value || '',
  };
}

function applySavedFilters() {
  try {
    const raw = localStorage.getItem(ADMIN_FILTER_CACHE_KEY);
    if (!raw) return;
    const saved = JSON.parse(raw);
    ['fFrom', 'fTo', 'fFactory', 'fType', 'fStatus', 'fPayment', 'fCompletion'].forEach((id) => {
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
  requestsMap = {};
  reqBody.innerHTML = '';
  (items || []).forEach(it => {
    const isBillUpload = (it.entry_type === 'simple_bill_upload')
      || String(it.item_category || '').trim().toLowerCase() === 'bill upload';
    if (isBillUpload) return;
    requestsMap[it.id] = it;
    const tr = document.createElement('tr');
    if (it.is_unread_admin) tr.classList.add('new-row');
    const reqType = escHtml(it.request_type || it.item_category || '—');
    const purposeFull = it.purpose || it.reason || '';
    const purpose = escHtml(purposeFull.substring(0, 50));
    const reqAmt = Number(it.final_amount || 0).toFixed(2);
    const paidAmt = Number(it.total_paid || 0).toFixed(2);
    const balance = Math.max(Number(it.final_amount || 0) - Number(it.total_paid || 0), 0).toFixed(2);
    const compStatus = it.completion_status || 'Pending';
    const approvalStatus = it.approval_status || 'Pending';
    const isPending = approvalStatus === 'Pending' || approvalStatus === 'Draft';
    const isPartial = approvalStatus === 'Partial Approved' || approvalStatus === 'Hold';
    const isCompSubmitted = compStatus === 'Completion Submitted';
    const isClosed = compStatus === 'Closed';

    tr.innerHTML = `
      <td>${it.id}</td>
      <td>${it.request_date}</td>
      <td>${escHtml(factoryNameFromId(it.factory_id))}</td>
      <td>${reqType}</td>
      <td title="${escHtml(purposeFull)}">${purpose}</td>
      <td>&#8377;${reqAmt}</td>
      <td>&#8377;${paidAmt}</td>
      <td>&#8377;${balance}</td>
      <td>${b(approvalStatus)}</td>
      <td>${b(it.payment_status)}</td>
      <td>${bComp(compStatus)}</td>
      <td>${escHtml(it.requested_by || '')}</td>
      <td class="d-flex flex-wrap gap-1">
        <button class="btn btn-sm btn-outline-secondary" onclick="viewDetails(${it.id})" title="View Details"><i class="bi bi-eye"></i></button>
        ${it.bill_image_path ? `<a target="_blank" class="btn btn-sm btn-outline-dark" href="/requests/${it.id}/bill" title="Bill"><i class="bi bi-file-earmark-image"></i></a>` : ''}
        ${(isPending || isPartial) ? `<button class="btn btn-sm btn-success" onclick="openApprove(${it.id})" title="${isPending ? 'Approve' : 'Add Payment'}"><i class="bi bi-${isPending ? 'check-lg' : 'plus-circle'}"></i> ${isPending ? 'Approve' : 'Pay'}</button>` : ''}
        ${(isPending || isPartial) ? `<button class="btn btn-sm btn-danger" onclick="openReject(${it.id})" title="Reject"><i class="bi bi-x-lg"></i></button>` : ''}
        ${isCompSubmitted ? `<button class="btn btn-sm btn-success" onclick="openVerify(${it.id})" title="Verify &amp; Close"><i class="bi bi-patch-check"></i> Verify</button>` : ''}
        ${(isCompSubmitted || isClosed) ? `<button class="btn btn-sm btn-warning text-dark" onclick="reopenRequest(${it.id})" title="Reopen"><i class="bi bi-arrow-counterclockwise"></i></button>` : ''}
        ${isPending ? `<button class="btn btn-sm btn-outline-danger" onclick="deleteRequest(${it.id})" title="Delete"><i class="bi bi-trash"></i></button>` : ''}
      </td>
    `;
    reqBody.appendChild(tr);
  });
}

function renderRequestLocation(item) {
  if (item.is_in_factory === true) {
    return '<span class="badge text-bg-success">In Factory</span>';
  }
  if (item.is_in_factory === false) {
    const dist = item.distance_from_factory_m != null ? `${Math.round(item.distance_from_factory_m)}m` : '';
    return `<span class="badge text-bg-danger">Outside</span> ${dist}`.trim();
  }
  if (item.geo_latitude != null && item.geo_longitude != null) {
    return '<span class="badge text-bg-secondary">GPS Captured</span>';
  }
  return '<span class="text-muted">No GPS</span>';
}

function presenceBadge(status) {
  if (status === 'In Factory') return '<span class="badge text-bg-success">In Factory</span>';
  if (status === 'Outside') return '<span class="badge text-bg-danger">Outside</span>';
  if (status === 'Offline') return '<span class="badge text-bg-secondary">Offline</span>';
  return '<span class="badge text-bg-warning">Unknown</span>';
}

async function loadPresenceUsers() {
  if (!presenceBody) return;
  const res = await fetch('/presence/users');
  if (!res.ok) return;
  const data = await res.json();
  presenceBody.innerHTML = '';
  (data.items || []).forEach((it) => {
    const tr = document.createElement('tr');
    const distance = it.distance_from_factory_m != null ? `${Math.round(it.distance_from_factory_m)} m` : '-';
    const accuracy = it.accuracy_m != null ? `${Math.round(it.accuracy_m)} m` : '-';
    const maps = (it.latitude != null && it.longitude != null)
      ? `<a target="_blank" class="btn btn-sm btn-outline-secondary" href="https://maps.google.com/?q=${it.latitude},${it.longitude}">Map</a>`
      : '<span class="text-muted">-</span>';
    tr.innerHTML = `
      <td>${it.user_name} <small class="text-muted">(${it.username})</small></td>
      <td>${it.factory || '-'}</td>
      <td>${presenceBadge(it.status)}</td>
      <td>${distance}</td>
      <td>${accuracy}</td>
      <td>${it.last_seen_at || '-'}</td>
      <td>${maps}</td>
    `;
    presenceBody.appendChild(tr);
  });
}
window.loadPresenceUsers = loadPresenceUsers;

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
  if (status === 'Pending')  return '<span class="badge badge-pending">⏳ Pending</span>';
  if (status === 'Approved') return '<span class="badge badge-approved">✅ Approved</span>';
  if (status === 'Rejected') return '<span class="badge badge-rejected">❌ Rejected</span>';
  if (status === 'Paid')     return '<span class="badge badge-paid">💳 Paid</span>';
  if (status === 'Partially Paid') return '<span class="badge badge-hold">🔶 Partially Paid</span>';
  if (status === 'Partial Approved' || status === 'Hold') return '<span class="badge badge-hold">🔶 Partial Approved</span>';
  if (status === 'Unpaid')   return '<span class="badge badge-draft">💰 Unpaid</span>';
  if (status === 'Draft')    return '<span class="badge badge-draft">📝 Draft</span>';
  return `<span class="badge badge-draft">${status || '—'}</span>`;
}

function bComp(status) {
  if (status === 'Pending') return '<span class="badge text-bg-secondary">— Pending</span>';
  if (status === 'Awaiting Completion') return '<span class="badge text-bg-warning text-dark">⏳ Awaiting</span>';
  if (status === 'Completion Submitted') return '<span class="badge text-bg-primary">📋 Submitted</span>';
  if (status === 'Closed') return '<span class="badge text-bg-success">✔ Closed</span>';
  return `<span class="badge text-bg-secondary">${status || '—'}</span>`;
}

async function loadRequests() {
  if (!reqBody) return;
  const params = new URLSearchParams();
  if (requestFilterActive) {
    const map = [
      ['from_date', 'fFrom'],
      ['to_date', 'fTo'],
      ['factory_id', 'fFactory'],
      ['request_type', 'fType'],
      ['status', 'fStatus'],
      ['payment_status', 'fPayment'],
      ['completion_status', 'fCompletion'],
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
    const isBillUpload = (it.entry_type === 'simple_bill_upload')
      || String(it.item_category || '').trim().toLowerCase() === 'bill upload';
    if (!isBillUpload) return;
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${it.id}</td>
      <td>${it.request_date}</td>
      <td>${it.vendor || ''}</td>
      <td>${it.requested_by || ''}</td>
      <td>${b(it.approval_status)}</td>
      <td>${it.bill_image_path ? `<a target="_blank" class="btn btn-sm btn-outline-secondary" href="/requests/${it.id}/bill">View Bill</a>` : '<span class="text-muted">No file</span>'}</td>
    `;
    simpleBillBody.appendChild(tr);
  });
}
window.loadSimpleBills = loadSimpleBills;

function clearFilters() {
  ['fFrom', 'fTo', 'fFactory', 'fType', 'fStatus', 'fPayment', 'fCompletion'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = '';
  });
  requestFilterActive = false;
  saveFilterState();
  loadRequests();
}
window.clearFilters = clearFilters;

function openApprove(id) {
  const req = requestsMap[id];
  if (!req) return;
  const finalAmt = Number(req.final_amount || 0);
  const paidAmt = Number(req.total_paid || 0);
  const balance = Math.max(finalAmt - paidAmt, 0);
  const isPending = req.approval_status === 'Pending' || req.approval_status === 'Draft';

  document.getElementById('approveRequestId').value = id;
  document.getElementById('approveReqAmt').textContent = '\u20B9' + finalAmt.toFixed(2);
  document.getElementById('approvePaidAmt').textContent = '\u20B9' + paidAmt.toFixed(2);
  document.getElementById('approveBalance').textContent = '\u20B9' + balance.toFixed(2);
  document.getElementById('approveAmtInput').value = '';
  document.getElementById('approveAmtInput').max = balance || finalAmt;
  document.getElementById('approveRemarks').value = '';
  document.getElementById('approveModalLabel').textContent = isPending ? 'Approve Request' : 'Release Additional Payment';
  document.getElementById('approveSubmitBtn').textContent = isPending ? 'Approve' : 'Release Payment';
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
  openApprove(id);
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

function openVerify(id) {
  const req = requestsMap[id];
  if (!req) return;
  document.getElementById('verifyRequestId').value = id;
  document.getElementById('verifyRemarks').value = '';
  const info = document.getElementById('verifyCompletionInfo');
  if (info) {
    const billLink = req.vendor_bill_path
      ? `<a href="/requests/${id}/vendor-bill" target="_blank" class="btn btn-sm btn-outline-primary me-2">📄 View Vendor Bill</a>`
      : '<span class="text-muted me-2">No vendor bill</span>';
    const voucherLink = req.company_voucher_path
      ? `<a href="/requests/${id}/company-voucher" target="_blank" class="btn btn-sm btn-outline-secondary">🧾 View Company Voucher</a>`
      : '<span class="text-muted">No company voucher</span>';
    const lines = [
      `<div class="mb-2"><strong>Request No:</strong> #${id} &nbsp;|&nbsp; <strong>Type:</strong> ${escHtml(req.request_type || req.item_category || '—')}</div>`,
      `<div class="mb-1"><strong>Purpose:</strong> ${escHtml(req.purpose || req.item_name || '—')}</div>`,
      req.completion_remark ? `<div class="mb-2 p-2 bg-light rounded"><strong>Completion Remark:</strong><br>${escHtml(req.completion_remark)}</div>` : '',
      req.completion_submitted_by_name ? `<div class="mb-1"><strong>Submitted By:</strong> ${escHtml(req.completion_submitted_by_name)}</div>` : '',
      req.completion_submitted_at ? `<div class="mb-2"><strong>Submitted At:</strong> ${escHtml(req.completion_submitted_at)}</div>` : '',
      `<div class="mb-1">${billLink}${voucherLink}</div>`,
    ].filter(Boolean);
    info.innerHTML = lines.length ? lines.join('') : '<span class="text-muted">No completion details</span>';
  }
  new bootstrap.Modal('#verifyModal').show();
}
window.openVerify = openVerify;

async function reopenRequest(id) {
  const reason = prompt('Reason for reopening (will be shown to factory user):');
  if (reason === null) return; // cancelled
  const fd = new FormData();
  if (reason.trim()) fd.append('reason', reason.trim());
  const res = await fetch(`/requests/${id}/reopen`, { method: 'POST', body: fd });
  const data = await res.json();
  alert(data.message || data.detail || 'Reopened');
  loadRequests();
}
window.reopenRequest = reopenRequest;

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
  const req = requestsMap[id];
  if (!req) return;
  const rows = [
    ['Request No', req.id],
    ['Date', req.request_date],
    ['Request Type', req.request_type || req.item_category || '—'],
    ['Purpose', req.purpose || req.reason || '—'],
    ['Factory', factoryNameFromId(req.factory_id)],
    ['Created By', req.requested_by || '—'],
    ['Requested Amount', '\u20B9' + Number(req.final_amount || 0).toFixed(2)],
    ['Total Paid', '\u20B9' + Number(req.total_paid || 0).toFixed(2)],
    ['Balance', '\u20B9' + Number(req.balance_amount || 0).toFixed(2)],
    ['Approval Status', req.approval_status || '—'],
    ['Payment Status', req.payment_status || '—'],
    ['Completion Status', req.completion_status || '—'],
    ['Approval Remark', req.approval_remark || '—'],
    ['Completion Remark', req.completion_remark || '—'],
    ['Submitted By', req.completion_submitted_by_name || '—'],
    ['Vendor Bill', req.vendor_bill_path ? `<a href="/requests/${req.id}/vendor-bill" target="_blank">📄 View Vendor Bill</a>` : '—'],
    ['Company Voucher', req.company_voucher_path ? `<a href="/requests/${req.id}/company-voucher" target="_blank">🧾 View Voucher</a>` : '—'],
    ['Completion Submitted', req.completion_submitted_at || '—'],
    ['Reopen Reason', req.reopen_reason || '—'],
    ['Verified Remark', req.verified_remark || '—'],
    ['Verified At', req.verified_at || '—'],
    ['Created At', req.created_at || '—'],
  ];
  const html = '<table class="table table-sm table-bordered">' +
    rows.map(([k, v]) => `<tr><th class="text-nowrap" style="width:40%">${escHtml(k)}</th><td>${v != null ? String(v) : '—'}</td></tr>`).join('') +
    '</table>';
  document.getElementById('viewModalBody').innerHTML = html;
  new bootstrap.Modal('#viewModal').show();
}
window.viewDetails = viewDetails;

document.getElementById('approveForm')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  const form = e.target;
  const id = form.request_id.value;
  const fd = new FormData(form);
  const res = await fetch(`/requests/${id}/partial-approve`, { method: 'POST', body: fd });
  const data = await res.json();
  if (!res.ok) {
    alert(data.detail || 'Cannot process approval');
    return;
  }
  alert(data.message || 'Updated');
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

document.getElementById('verifyForm')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  const id = document.getElementById('verifyRequestId').value;
  const fd = new FormData(e.target);
  const res = await fetch(`/requests/${id}/verify`, { method: 'POST', body: fd });
  const data = await res.json();
  if (!res.ok) {
    alert(data.detail || 'Cannot verify');
    return;
  }
  alert(data.message || 'Verified and closed');
  bootstrap.Modal.getInstance(document.getElementById('verifyModal'))?.hide();
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
    loadPresenceUsers();
  }
}, 12000);

applySavedFilters();
restoreRequestsFromCache();
pollNotifications();
loadRequests();
loadSimpleBills();
loadPresenceUsers();

async function checkStorageHealth() {
  const badge = document.getElementById('storageBadge');
  const detail = document.getElementById('storageDetail');
  badge.className = 'badge text-bg-secondary';
  badge.textContent = 'Checking…';
  detail.textContent = '';
  try {
    const res = await fetch('/health/storage');
    const d = await res.json();
    if (d.ok) {
      badge.className = 'badge text-bg-success';
      badge.textContent = (d.backend === 'local' ? 'Local ✓' : `R2 ✓`);
      detail.textContent = d.latency_ms !== undefined
        ? `${d.bucket}  ${d.latency_ms} ms`
        : d.path || '';
    } else {
      badge.className = 'badge text-bg-danger';
      badge.textContent = `${d.backend} ✗`;
      detail.textContent = d.error || 'Unknown error';
    }
  } catch (e) {
    badge.className = 'badge text-bg-danger';
    badge.textContent = 'Error';
    detail.textContent = e.message;
  }
}
window.checkStorageHealth = checkStorageHealth;
checkStorageHealth();
