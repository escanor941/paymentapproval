const requestForm = document.getElementById('requestForm');
const ownTableBody = document.querySelector('#ownTable tbody');
const qtyInput = document.getElementById('qty');
const rateInput = document.getElementById('rate');
const gstInput = document.getElementById('gst');
const amountInput = document.getElementById('amount');
const finalAmountInput = document.getElementById('final_amount');
const flashBox = document.getElementById('factoryFlash');
const simpleBillForm = document.getElementById('simpleBillForm');
const simpleBillFlashBox = document.getElementById('simpleBillFlash');
let editRequestId = null;

// ---- Factory status-change notification system ----
let factoryStatusMap = {};
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
  if (navigator.vibrate) {
    navigator.vibrate([200, 100, 300, 100, 400]);
  }
  playNotifSound();
  if ('Notification' in window && Notification.permission === 'granted') {
    try { new Notification(title, { body: message }); } catch (e) {}
  }
  showOverlayNotif(title, message, type);
  showToast(`${title} — ${message}`, type);
}

function checkStatusChanges(items) {
  if (!factoryNotifInitialized) {
    items.forEach(item => { factoryStatusMap[item.id] = item.approval_status; });
    factoryNotifInitialized = true;
    return;
  }
  items.forEach(item => {
    const prev = factoryStatusMap[item.id];
    if (prev !== undefined && prev !== item.approval_status) {
      let title, message, type;
      if (item.approval_status === 'Approved') {
        title = 'Request Approved!';
        message = `"${item.item_name}" has been APPROVED.`;
        type = 'success';
      } else if (item.approval_status === 'Rejected') {
        const reason = item.approval_remark ? ` Reason: ${item.approval_remark}` : '';
        title = 'Request Rejected';
        message = `"${item.item_name}" was rejected.${reason}`;
        type = 'danger';
      } else if (item.approval_status === 'Hold') {
        title = 'Request On Hold';
        message = `"${item.item_name}" has been put on hold.`;
        type = 'warning';
      } else {
        title = 'Request Updated';
        message = `"${item.item_name}" status changed to ${item.approval_status}.`;
        type = 'info';
      }
      showStrongNotification(title, message, type);
    }
    factoryStatusMap[item.id] = item.approval_status;
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

  requestAnimationFrame(() => {
    toast.classList.add('show');
  });

  setTimeout(() => {
    toast.classList.remove('show');
    setTimeout(() => toast.remove(), 220);
  }, 2600);
}

function showFlash(message, type = 'success') {
  if (!flashBox) return;
  flashBox.innerHTML = `<div class="alert alert-${type} py-2 mb-0">${message}</div>`;
  setTimeout(() => {
    flashBox.innerHTML = '';
  }, 3000);
}

function showSimpleFlash(message, type = 'success') {
  if (!simpleBillFlashBox) return;
  simpleBillFlashBox.innerHTML = `<div class="alert alert-${type} py-2 mb-0">${message}</div>`;
  setTimeout(() => {
    simpleBillFlashBox.innerHTML = '';
  }, 3000);
}

function calcAmounts() {
  const qty = parseFloat(qtyInput?.value || 0);
  const rate = parseFloat(rateInput?.value || 0);
  const gst = parseFloat(gstInput?.value || 0);
  const amount = qty * rate;
  const finalAmount = amount + (amount * gst / 100);
  if (amountInput) amountInput.value = amount.toFixed(2);
  if (finalAmountInput) finalAmountInput.value = finalAmount.toFixed(2);
}

[qtyInput, rateInput, gstInput].forEach(el => el?.addEventListener('input', calcAmounts));

if (requestForm) {
  const date = new Date().toISOString().slice(0, 10);
  requestForm.querySelector('[name="request_date"]').value = date;

  requestForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    await submitRequest(false);
  });
}

if (simpleBillForm) {
  simpleBillForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    await submitSimpleBill();
  });
}

async function submitRequest(saveAsDraft) {
  if (!requestForm) return;
  const formData = new FormData(requestForm);
  const submitBtn = requestForm.querySelector('button[type="submit"]');
  const draftBtn = requestForm.querySelector('button[onclick="saveDraft()"]');
  const resetBtn = requestForm.querySelector('button[type="reset"]');
  const defaultSubmitText = submitBtn?.textContent || 'Submit Request';
  const defaultDraftText = draftBtn?.textContent || 'Save Draft';

  // Bill image is mandatory for final submissions (not drafts)
  if (!saveAsDraft) {
    const billFile = formData.get('bill_image');
    if (!billFile || billFile.size === 0) {
      showFlash('Upload Bill / Quotation Image is required before submitting.', 'danger');
      document.querySelector('[name="bill_image"]')?.focus();
      return;
    }
  }

  formData.set('save_as_draft', saveAsDraft ? 'true' : 'false');
  if (formData.get('urgent_flag') === 'true') {
    formData.set('urgent_flag', 'true');
  } else {
    formData.set('urgent_flag', 'false');
  }

  const url = editRequestId ? `/requests/${editRequestId}` : '/requests';
  const method = editRequestId ? 'PUT' : 'POST';
  const startTime = performance.now();

  if (submitBtn) {
    submitBtn.disabled = true;
    submitBtn.textContent = saveAsDraft ? 'Saving...' : 'Submitting...';
  }
  if (draftBtn) {
    draftBtn.disabled = true;
    if (saveAsDraft) draftBtn.textContent = 'Saving...';
  }
  if (resetBtn) resetBtn.disabled = true;

  showFlash(saveAsDraft ? 'Saving draft...' : 'Uploading bill and submitting request, please wait...', 'info');

  try {
    const res = await fetch(url, { method, body: formData });
    const data = await res.json();
    if (!res.ok) {
      showFlash(data.detail || data.message || 'Failed to save request', 'danger');
      showToast(data.detail || data.message || 'Failed to save request', 'danger');
      return;
    }

    showFlash(data.message || 'Request saved', 'success');
    const seconds = ((performance.now() - startTime) / 1000).toFixed(1);
    showToast(`${data.message || 'Request saved'} (${seconds}s)`, 'success');
  } catch (err) {
    showFlash('Network error while saving request', 'danger');
    showToast('Network error while saving request', 'danger');
    return;
  } finally {
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.textContent = defaultSubmitText;
    }
    if (draftBtn) {
      draftBtn.disabled = false;
      draftBtn.textContent = defaultDraftText;
    }
    if (resetBtn) resetBtn.disabled = false;
  }

  editRequestId = null;
  requestForm.reset();
  requestForm.querySelector('[name="request_date"]').value = new Date().toISOString().slice(0, 10);
  calcAmounts();
  loadOwnRequests();
}

async function saveDraft() {
  await submitRequest(true);
}
window.saveDraft = saveDraft;

async function submitSimpleBill() {
  if (!simpleBillForm) return;
  const fd = new FormData(simpleBillForm);
  const submitBtn = simpleBillForm.querySelector('button[type="submit"]');
  const resetBtn = simpleBillForm.querySelector('button[type="reset"]');
  const defaultSubmitText = submitBtn?.textContent || 'Upload Bill';
  const startTime = performance.now();
  const billFile = fd.get('bill_image');
  const vendorName = (fd.get('vendor_name') || '').toString().trim();
  if (!vendorName) {
    showSimpleFlash('Vendor name is required.', 'danger');
    return;
  }
  if (!billFile || billFile.size === 0) {
    showSimpleFlash('Actual bill image is required.', 'danger');
    return;
  }

  if (submitBtn) {
    submitBtn.disabled = true;
    submitBtn.textContent = 'Uploading...';
  }
  if (resetBtn) resetBtn.disabled = true;
  showSimpleFlash('Uploading bill, please wait...', 'info');

  try {
    const res = await fetch('/requests/simple-bill', { method: 'POST', body: fd });
    const data = await res.json();
    if (!res.ok) {
      showSimpleFlash(data.detail || 'Failed to upload bill', 'danger');
      showToast(data.detail || 'Failed to upload bill', 'danger');
      return;
    }
    showSimpleFlash(data.message || 'Bill uploaded', 'success');
    const seconds = ((performance.now() - startTime) / 1000).toFixed(1);
    showToast(`${data.message || 'Bill uploaded'} (${seconds}s)`, 'success');
    simpleBillForm.reset();
    loadOwnRequests();
  } catch (err) {
    showSimpleFlash('Network error while uploading bill', 'danger');
    showToast('Network error while uploading bill', 'danger');
  } finally {
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.textContent = defaultSubmitText;
    }
    if (resetBtn) resetBtn.disabled = false;
  }
}

function badge(status) {
  if (status === 'Pending') return '<span class="badge badge-pending">Pending</span>';
  if (status === 'Approved') return '<span class="badge badge-approved">Approved</span>';
  if (status === 'Rejected') return '<span class="badge badge-rejected">Rejected</span>';
  if (status === 'Paid') return '<span class="badge badge-paid">Paid</span>';
  return `<span class="badge text-bg-secondary">${status}</span>`;
}

async function loadOwnRequests() {
  if (!ownTableBody) return;
  const params = new URLSearchParams();
  const d = document.getElementById('fsDate')?.value;
  const v = document.getElementById('fsVendor')?.value;
  const s = document.getElementById('fsStatus')?.value;
  if (d) {
    params.set('from_date', d);
    params.set('to_date', d);
  }
  if (v) params.set('vendor', v);
  if (s) params.set('status', s);

  const res = await fetch(`/requests?${params.toString()}`);
  const data = await res.json();
  checkStatusChanges(data.items);
  ownTableBody.innerHTML = '';

  data.items.filter(item => item.approval_status !== 'Approved').forEach(item => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td data-label="ID">${item.id}</td>
      <td data-label="Date">${item.request_date}</td>
      <td data-label="Vendor">${item.vendor || ''}</td>
      <td data-label="Item">${item.item_name}</td>
      <td data-label="Amount">${item.final_amount.toFixed ? item.final_amount.toFixed(2) : item.final_amount}</td>
      <td data-label="Approval">${badge(item.approval_status)}</td>
      <td data-label="Payment">${badge(item.payment_status)}</td>
      <td data-label="Actions" class="actions-cell">
        ${['Pending','Draft','Hold'].includes(item.approval_status) ? `<button class="btn btn-sm btn-outline-primary" onclick="editOwn(${item.id})">Edit</button>` : ''}
        ${['Pending','Draft','Hold'].includes(item.approval_status) ? `<button class="btn btn-sm btn-outline-danger" onclick="deleteOwn(${item.id})">Delete</button>` : ''}
        ${item.bill_image_path ? `<a class="btn btn-sm btn-outline-secondary" target="_blank" href="${item.bill_image_path}">Bill</a>` : ''}
      </td>
    `;
    ownTableBody.appendChild(tr);
  });
}
window.loadOwnRequests = loadOwnRequests;

async function deleteOwn(id) {
  if (!confirm('Delete this request?')) return;
  const res = await fetch(`/requests/${id}`, { method: 'DELETE' });
  const data = await res.json();
  if (!res.ok) {
    showFlash(data.detail || 'Unable to delete request', 'danger');
    return;
  }
  showFlash(data.message || 'Deleted', 'success');
  loadOwnRequests();
}
window.deleteOwn = deleteOwn;

async function editOwn(id) {
  const res = await fetch('/requests');
  const data = await res.json();
  const item = (data.items || []).find(x => x.id === id);
  if (!item) return;

  editRequestId = id;
  requestForm.querySelector('[name="request_date"]').value = item.request_date;
  requestForm.querySelector('[name="factory_id"]').value = item.factory_id;
  requestForm.querySelector('[name="vendor_id"]').value = item.vendor_id;
  requestForm.querySelector('[name="vendor_mobile"]').value = item.vendor_mobile || '';
  requestForm.querySelector('[name="item_category"]').value = item.item_category;
  requestForm.querySelector('[name="item_name"]').value = item.item_name;
  requestForm.querySelector('[name="qty"]').value = item.qty;
  requestForm.querySelector('[name="unit"]').value = item.unit;
  requestForm.querySelector('[name="rate"]').value = item.rate;
  requestForm.querySelector('[name="gst_percent"]').value = item.gst_percent || 0;
  requestForm.querySelector('[name="reason"]').value = item.reason;
  requestForm.querySelector('[name="urgent_flag"]').value = item.urgent_flag ? 'true' : 'false';
  requestForm.querySelector('[name="requested_by"]').value = item.requested_by;
  requestForm.querySelector('[name="notes"]').value = item.notes || '';
  calcAmounts();
  window.scrollTo({ top: 0, behavior: 'smooth' });
}
window.editOwn = editOwn;

initFactoryNotifications();
calcAmounts();
loadOwnRequests();
setInterval(loadOwnRequests, 10000);
