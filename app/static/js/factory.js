// ============================================================
// Factory Panel — v2 (simplified request workflow)
// ============================================================

const factoryRequestForm = document.getElementById('factoryRequestForm');
const ownTableBody = document.querySelector('#ownTable tbody');
const awaitingTableBody = document.querySelector('#awaitingTable tbody');
const awaitingSection = document.getElementById('awaitingSection');
const flashBox = document.getElementById('factoryFlash');

let geoWarned = false;

// ---- Status-change notification system ----
let factoryStatusMap = {};
let factoryCompletionMap = {};
let factoryNotifInitialized = false;

function initFactoryNotifications() {
  if ('Notification' in window && Notification.permission === 'default') {
    Notification.requestPermission().catch(() => {});
  }
}

function playNotifSound() {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.type = 'sine';
    osc.frequency.setValueAtTime(880, ctx.currentTime);
    osc.frequency.exponentialRampToValueAtTime(440, ctx.currentTime + 0.25);
    gain.gain.setValueAtTime(0.7, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.45);
    osc.start(ctx.currentTime);
    osc.stop(ctx.currentTime + 0.5);
  } catch (e) {}
}

function showOverlayNotif(title, message, type) {
  const iconMap = { success: '✓', danger: '✕', warning: '⏸', info: 'ℹ' };
  const existing = document.querySelector('.factory-notif-overlay');
  if (existing) existing.remove();

  const overlay = document.createElement('div');
  overlay.className = 'factory-notif-overlay';
  overlay.innerHTML = `
    <div class="factory-notif-box factory-notif-box-${type}">
      <div class="factory-notif-icon factory-notif-icon-${type}">${iconMap[type] || 'ℹ'}</div>
      <div class="factory-notif-title">${title}</div>
      <div class="factory-notif-msg">${message}</div>
      <button class="factory-notif-ok" onclick="this.closest('.factory-notif-overlay').remove()">OK</button>
    </div>
  `;
  document.body.appendChild(overlay);
  requestAnimationFrame(() => overlay.classList.add('show'));

  const autoDismiss = setTimeout(() => {
    overlay.classList.remove('show');
    setTimeout(() => overlay.remove(), 300);
  }, 8000);

  overlay.querySelector('.factory-notif-ok').addEventListener('click', () => {
    clearTimeout(autoDismiss);
  });
  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) {
      clearTimeout(autoDismiss);
      overlay.remove();
    }
  });
}

function showStrongNotification(title, message, type) {
  if (navigator.vibrate) navigator.vibrate([200, 100, 300, 100, 400]);
  playNotifSound();
  if ('Notification' in window && Notification.permission === 'granted') {
    try { new Notification(title, { body: message }); } catch (e) {}
  }
  showOverlayNotif(title, message, type);
  showToast(`${title} — ${message}`, type);
}

function checkStatusChanges(items) {
  if (!factoryNotifInitialized) {
    items.forEach(item => {
      factoryStatusMap[item.id] = item.approval_status;
      factoryCompletionMap[item.id] = item.completion_status;
    });
    factoryNotifInitialized = true;
    return;
  }
  items.forEach(item => {
    const prevApproval = factoryStatusMap[item.id];
    if (prevApproval !== undefined && prevApproval !== item.approval_status) {
      let title, message, type;
      if (item.approval_status === 'Approved') {
        title = 'Request Approved!';
        message = `Request #${item.id} has been APPROVED.`;
        type = 'success';
      } else if (item.approval_status === 'Rejected') {
        const reason = item.approval_remark ? ` Reason: ${item.approval_remark}` : '';
        title = 'Request Rejected';
        message = `Request #${item.id} was rejected.${reason}`;
        type = 'danger';
      } else if (item.approval_status === 'Partial Approved') {
        title = 'Partially Approved';
        message = `Request #${item.id} has been partially approved.`;
        type = 'warning';
      } else {
        title = 'Request Updated';
        message = `Request #${item.id} status changed to ${item.approval_status}.`;
        type = 'info';
      }
      showStrongNotification(title, message, type);
    }
    factoryStatusMap[item.id] = item.approval_status;

    const prevCompletion = factoryCompletionMap[item.id];
    if (prevCompletion !== undefined && prevCompletion !== item.completion_status) {
      if (item.completion_status === 'Awaiting Completion') {
        showStrongNotification(
          'Action Required: Submit Completion',
          `Request #${item.id} has been fully paid. Please submit completion details.`,
          'warning'
        );
      }
    }
    factoryCompletionMap[item.id] = item.completion_status;
  });
}

function showToast(message, type = 'success') {
  let container = document.getElementById('factoryToastContainer');
  if (!container) {
    container = document.createElement('div');
    container.id = 'factoryToastContainer';
    container.className = 'factory-toast-container';
    document.body.appendChild(container);
  }
  const toast = document.createElement('div');
  toast.className = `factory-toast factory-toast-${type}`;
  toast.textContent = message;
  container.appendChild(toast);
  requestAnimationFrame(() => toast.classList.add('show'));
  setTimeout(() => {
    toast.classList.remove('show');
    setTimeout(() => toast.remove(), 220);
  }, 2600);
}

function showFlash(message, type = 'success') {
  if (!flashBox) return;
  flashBox.innerHTML = `<div class="alert alert-${type} py-2 mb-0">${message}</div>`;
  setTimeout(() => { flashBox.innerHTML = ''; }, 4000);
}

function showCompletionFlash(message, type = 'success') {
  const box = document.getElementById('completionFlash');
  if (!box) return;
  box.innerHTML = `<div class="alert alert-${type} py-2 mb-0">${message}</div>`;
}

// ---- Geolocation helpers ----
function getCurrentLocation(timeoutMs = 8000) {
  return new Promise((resolve) => {
    if (!navigator.geolocation) { resolve(null); return; }
    navigator.geolocation.getCurrentPosition(
      (pos) => resolve({ latitude: pos.coords.latitude, longitude: pos.coords.longitude, accuracy: pos.coords.accuracy }),
      () => resolve(null),
      { enableHighAccuracy: true, timeout: timeoutMs, maximumAge: 30000 }
    );
  });
}

async function attachLocationToFormData(formData) {
  const loc = await getCurrentLocation();
  if (!loc) {
    if (!geoWarned) {
      showToast('Location unavailable. Request will be submitted without GPS.', 'warning');
      geoWarned = true;
    }
    return;
  }
  formData.set('geo_latitude', String(loc.latitude));
  formData.set('geo_longitude', String(loc.longitude));
  formData.set('geo_accuracy_m', String(loc.accuracy || 0));
}

async function sendPresencePing() {
  const loc = await getCurrentLocation(7000);
  if (!loc) return;
  const fd = new FormData();
  fd.set('latitude', String(loc.latitude));
  fd.set('longitude', String(loc.longitude));
  fd.set('accuracy_m', String(loc.accuracy || 0));
  const fid = factoryRequestForm?.querySelector('[name="factory_id"]')?.value || '';
  if (fid) fd.set('factory_id', fid);
  try { await fetch('/presence/ping', { method: 'POST', body: fd }); } catch (_) {}
}

// ---- Create Request ----
if (factoryRequestForm) {
  factoryRequestForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    await submitFactoryRequest();
  });
}

async function submitFactoryRequest() {
  if (!factoryRequestForm) return;
  const formData = new FormData(factoryRequestForm);
  const submitBtn = document.getElementById('factorySubmitBtn');
  const defaultText = submitBtn?.textContent || 'Submit Request';

  const requestType = (formData.get('request_type') || '').trim();
  const purpose = (formData.get('purpose') || '').trim();
  const amount = parseFloat(formData.get('amount') || '0');

  if (!requestType) { showFlash('Please select a Request Type.', 'danger'); return; }
  if (!purpose) { showFlash('Purpose is required.', 'danger'); return; }
  if (!amount || amount <= 0) { showFlash('Amount must be greater than zero.', 'danger'); return; }

  await attachLocationToFormData(formData);

  if (submitBtn) { submitBtn.disabled = true; submitBtn.textContent = 'Submitting…'; }
  showFlash('Submitting request, please wait…', 'info');

  try {
    const res = await fetch('/requests/factory', { method: 'POST', body: formData });
    const data = await res.json();
    if (!res.ok) {
      showFlash(data.detail || data.message || 'Failed to submit request', 'danger');
      showToast(data.detail || 'Submission failed', 'danger');
      return;
    }
    showFlash(data.message || 'Request submitted successfully!', 'success');
    showToast(data.message || 'Request submitted!', 'success');
    factoryRequestForm.reset();
    // Switch to My Requests tab
    const myReqTab = document.getElementById('myreq-tab');
    if (myReqTab) myReqTab.click();
    loadOwnRequests();
  } catch (err) {
    showFlash('Network error while submitting request.', 'danger');
    showToast('Network error', 'danger');
  } finally {
    if (submitBtn) { submitBtn.disabled = false; submitBtn.textContent = defaultText; }
  }
}

// ---- Badges ----
function approvalBadge(status) {
  const map = {
    'Pending': 'badge-pending',
    'Approved': 'badge-approved',
    'Rejected': 'badge-rejected',
    'Partial Approved': 'badge-warning text-dark',
  };
  const cls = map[status] || 'text-bg-secondary';
  return `<span class="badge ${cls}">${status}</span>`;
}

function paymentBadge(status) {
  const map = { 'Unpaid': 'text-bg-secondary', 'Partially Paid': 'badge-warning text-dark', 'Paid': 'badge-paid' };
  const cls = map[status] || 'text-bg-secondary';
  return `<span class="badge ${cls}">${status}</span>`;
}

function completionBadge(status) {
  if (status === 'Awaiting Completion') return `<span class="badge bg-warning text-dark">${status}</span>`;
  if (status === 'Completion Submitted') return `<span class="badge bg-success">${status}</span>`;
  return `<span class="badge text-bg-secondary">${status || 'Pending'}</span>`;
}

// ---- Load Requests ----
async function loadOwnRequests() {
  if (!ownTableBody) return;
  const params = new URLSearchParams();
  const d = document.getElementById('fsDate')?.value;
  const s = document.getElementById('fsStatus')?.value;
  const c = document.getElementById('fsCompletion')?.value;
  if (d) { params.set('from_date', d); params.set('to_date', d); }
  if (s) params.set('status', s);

  const res = await fetch(`/requests?${params.toString()}`);
  const data = await res.json();
  checkStatusChanges(data.items);

  let filtered = data.items;
  if (c) filtered = filtered.filter(item => (item.completion_status || 'Pending') === c);

  // ---- Awaiting Completion section ----
  const awaiting = data.items.filter(item => (item.completion_status || 'Pending') === 'Awaiting Completion');
  if (awaitingSection) awaitingSection.style.display = awaiting.length ? '' : 'none';
  if (awaitingTableBody) {
    awaitingTableBody.innerHTML = '';
    awaiting.forEach(item => {
      const tr = document.createElement('tr');
      tr.className = 'table-warning';
      tr.innerHTML = `
        <td>#${item.id}</td>
        <td>${item.request_date}</td>
        <td>${item.request_type || item.item_category || ''}</td>
        <td>${escHtml(item.purpose || item.reason || '')}</td>
        <td>₹${fmtAmt(item.final_amount)}</td>
        <td><button class="btn btn-sm btn-success" onclick="openCompletionModal(${item.id}, '${escHtml(item.request_type || item.item_category || '')}')">Submit Completion</button></td>
      `;
      awaitingTableBody.appendChild(tr);
    });
  }

  // ---- Main table ----
  ownTableBody.innerHTML = '';
  filtered.forEach(item => {
    const completionSt = item.completion_status || 'Pending';
    const canEdit = ['Pending', 'Draft'].includes(item.approval_status);
    const canDelete = ['Pending', 'Draft'].includes(item.approval_status);
    const canComplete = completionSt === 'Awaiting Completion';

    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td data-label="Req No">#${item.id}</td>
      <td data-label="Date">${item.request_date}</td>
      <td data-label="Type">${item.request_type || item.item_category || ''}</td>
      <td data-label="Purpose">${escHtml(item.purpose || item.reason || '')}</td>
      <td data-label="Amount">₹${fmtAmt(item.final_amount)}</td>
      <td data-label="Approval">${approvalBadge(item.approval_status)}</td>
      <td data-label="Payment">${paymentBadge(item.payment_status)}</td>
      <td data-label="Completion">${completionBadge(completionSt)}</td>
      <td data-label="Actions" class="actions-cell">
        ${canDelete ? `<button class="btn btn-sm btn-outline-danger" onclick="deleteOwn(${item.id})">Delete</button>` : ''}
        ${canComplete ? `<button class="btn btn-sm btn-success" onclick="openCompletionModal(${item.id}, '${escHtml(item.request_type || item.item_category || '')}')">Complete</button>` : ''}
        ${item.bill_image_path ? `<a class="btn btn-sm btn-outline-secondary" target="_blank" href="/requests/${item.id}/bill">Bill</a>` : ''}
        ${item.completion_bill_path ? `<a class="btn btn-sm btn-outline-info" target="_blank" href="${item.completion_bill_path}">Inv</a>` : ''}
      </td>
    `;
    ownTableBody.appendChild(tr);
  });
}
window.loadOwnRequests = loadOwnRequests;

function fmtAmt(v) {
  const n = parseFloat(v);
  return isNaN(n) ? '0.00' : n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function escHtml(str) {
  return String(str || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ---- Delete ----
async function deleteOwn(id) {
  if (!confirm('Delete this request?')) return;
  const res = await fetch(`/requests/${id}`, { method: 'DELETE' });
  const data = await res.json();
  if (!res.ok) { showToast(data.detail || 'Unable to delete request', 'danger'); return; }
  showToast(data.message || 'Deleted', 'success');
  loadOwnRequests();
}
window.deleteOwn = deleteOwn;

// ---- Completion Modal ----
let completionModalInstance = null;

function openCompletionModal(requestId, requestType) {
  document.getElementById('completionRequestId').value = requestId;
  document.getElementById('completionRemark').value = '';
  document.getElementById('completionFlash').innerHTML = '';
  document.getElementById('completionForm').reset();
  document.getElementById('completionRequestId').value = requestId;

  // Show/hide type-specific fields
  const transportFields = document.getElementById('transportFields');
  const fileField = document.getElementById('completionFileField');
  const fileLabel = document.getElementById('completionFileLabel');

  transportFields.style.display = requestType === 'Transport' ? '' : 'none';
  if (requestType === 'Material') {
    fileField.style.display = '';
    fileLabel.textContent = 'Upload Bill (Optional)';
  } else if (requestType === 'Service') {
    fileField.style.display = '';
    fileLabel.textContent = 'Upload Invoice (Optional)';
  } else {
    fileField.style.display = 'none';
  }

  if (!completionModalInstance) {
    const el = document.getElementById('completionModal');
    completionModalInstance = new bootstrap.Modal(el);
  }
  completionModalInstance.show();
}
window.openCompletionModal = openCompletionModal;

async function submitCompletion() {
  const form = document.getElementById('completionForm');
  const requestId = document.getElementById('completionRequestId').value;
  const remark = (document.getElementById('completionRemark').value || '').trim();

  if (!remark) {
    showCompletionFlash('Completion remark is required.', 'danger');
    return;
  }

  const formData = new FormData(form);
  const btn = document.getElementById('completionSubmitBtn');
  const defaultText = btn?.textContent || 'Submit Completion';
  if (btn) { btn.disabled = true; btn.textContent = 'Submitting…'; }
  showCompletionFlash('Submitting…', 'info');

  try {
    const res = await fetch(`/requests/${requestId}/complete`, { method: 'POST', body: formData });
    const data = await res.json();
    if (!res.ok) {
      showCompletionFlash(data.detail || 'Failed to submit completion', 'danger');
      return;
    }
    showCompletionFlash(data.message || 'Completion submitted!', 'success');
    showToast('Completion submitted successfully!', 'success');
    setTimeout(() => {
      completionModalInstance?.hide();
      loadOwnRequests();
    }, 1200);
  } catch (err) {
    showCompletionFlash('Network error while submitting completion.', 'danger');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = defaultText; }
  }
}
window.submitCompletion = submitCompletion;

// ---- Init ----
initFactoryNotifications();
loadOwnRequests();
sendPresencePing();
setInterval(() => { if (!document.hidden) sendPresencePing(); }, 60000);
setInterval(() => { if (!document.hidden) loadOwnRequests(); }, 10000);


