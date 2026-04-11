const masterTableBody = document.querySelector('#masterTable tbody');

async function loadMaster() {
  const type = document.getElementById('masterType').value;
  const res = await fetch(`/masters/${type}`);
  const data = await res.json();
  masterTableBody.innerHTML = '';
  (data.items || []).forEach(item => {
    const detail = [item.location, item.mobile, item.address, item.gst_no].filter(Boolean).join(' | ');
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${item.id}</td>
      <td>${item.name || ''}</td>
      <td>${detail}</td>
      <td>
        <button class="btn btn-sm btn-outline-primary" onclick="editMaster(${item.id}, '${(item.name || '').replace(/'/g, "\\'")}')">Edit</button>
        <button class="btn btn-sm btn-outline-danger" onclick="deleteMaster(${item.id})">Delete</button>
      </td>
    `;
    masterTableBody.appendChild(tr);
  });
}
window.loadMaster = loadMaster;

async function createMaster() {
  const type = document.getElementById('masterType').value;
  const payload = {
    name: document.getElementById('mName').value,
    extra1: document.getElementById('mExtra1').value,
    extra2: document.getElementById('mExtra2').value,
    extra3: document.getElementById('mExtra3').value,
  };
  const res = await fetch(`/masters/${type}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  alert(data.message || data.detail || 'Saved');
  loadMaster();
}
window.createMaster = createMaster;

async function editMaster(id, name) {
  const type = document.getElementById('masterType').value;
  const newName = prompt('New name:', name);
  if (!newName) return;
  const payload = {
    name: newName,
    extra1: document.getElementById('mExtra1').value,
    extra2: document.getElementById('mExtra2').value,
    extra3: document.getElementById('mExtra3').value,
  };
  const res = await fetch(`/masters/${type}/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  alert(data.message || data.detail || 'Updated');
  loadMaster();
}
window.editMaster = editMaster;

async function deleteMaster(id) {
  const type = document.getElementById('masterType').value;
  if (!confirm('Delete item?')) return;
  const res = await fetch(`/masters/${type}/${id}`, { method: 'DELETE' });
  const data = await res.json();
  alert(data.message || data.detail || 'Deleted');
  loadMaster();
}
window.deleteMaster = deleteMaster;

document.getElementById('masterType')?.addEventListener('change', loadMaster);
loadMaster();
