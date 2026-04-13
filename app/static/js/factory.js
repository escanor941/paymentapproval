const requestForm = document.getElementById('requestForm');
const ownTableBody = document.querySelector('#ownTable tbody');
const qtyInput = document.getElementById('qty');
const rateInput = document.getElementById('rate');
const gstInput = document.getElementById('gst');
const amountInput = document.getElementById('amount');
const finalAmountInput = document.getElementById('final_amount');
const flashBox = document.getElementById('factoryFlash');
let editRequestId = null;

function showFlash(message, type = 'success') {
  if (!flashBox) return;
  flashBox.innerHTML = `<div class="alert alert-${type} py-2 mb-0">${message}</div>`;
  setTimeout(() => {
    flashBox.innerHTML = '';
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

async function submitRequest(saveAsDraft) {
  const formData = new FormData(requestForm);
  formData.set('save_as_draft', saveAsDraft ? 'true' : 'false');
  if (formData.get('urgent_flag') === 'true') {
    formData.set('urgent_flag', 'true');
  } else {
    formData.set('urgent_flag', 'false');
  }

  const url = editRequestId ? `/requests/${editRequestId}` : '/requests';
  const method = editRequestId ? 'PUT' : 'POST';
  try {
    const res = await fetch(url, { method, body: formData });
    const data = await res.json();
    if (!res.ok) {
      showFlash(data.detail || data.message || 'Failed to save request', 'danger');
      return;
    }

    showFlash(data.message || 'Request saved', 'success');
  } catch (err) {
    showFlash('Network error while saving request', 'danger');
    return;
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
  ownTableBody.innerHTML = '';

  data.items.forEach(item => {
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

calcAmounts();
loadOwnRequests();
