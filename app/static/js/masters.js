const masterTableBody = document.querySelector('#masterTable tbody');

function updateMasterFieldHints() {
  const type = document.getElementById('masterType')?.value;
  const lName = document.querySelector('label[for="mName"]') || document.querySelector('#mName')?.previousElementSibling;
  const lExtra1 = document.querySelector('label[for="mExtra1"]') || document.querySelector('#mExtra1')?.previousElementSibling;
  const lExtra2 = document.querySelector('label[for="mExtra2"]') || document.querySelector('#mExtra2')?.previousElementSibling;
  const lExtra3 = document.querySelector('label[for="mExtra3"]') || document.querySelector('#mExtra3')?.previousElementSibling;
  const e1 = document.getElementById('mExtra1');
  const e2 = document.getElementById('mExtra2');
  const e3 = document.getElementById('mExtra3');
  const helper = document.getElementById('factoryLocationHelper');

  if (lName) lName.textContent = 'Name';
  if (lExtra1) lExtra1.textContent = 'Extra 1';
  if (lExtra2) lExtra2.textContent = 'Extra 2';
  if (lExtra3) lExtra3.textContent = 'Extra 3';

  if (e1) e1.placeholder = '';
  if (e2) e2.placeholder = '';
  if (e3) e3.placeholder = '';

  if (helper) helper.classList.add('d-none');

  if (type === 'factories') {
    if (lExtra1) lExtra1.textContent = 'Location (lat,long,radius)';
    if (e1) e1.placeholder = '12.9716,77.5946,250';
    if (helper) helper.classList.remove('d-none');
  } else if (type === 'vendors') {
    if (lExtra1) lExtra1.textContent = 'Mobile';
    if (lExtra2) lExtra2.textContent = 'Address';
    if (lExtra3) lExtra3.textContent = 'GST No';
  } else if (type === 'users') {
    if (lExtra1) lExtra1.textContent = 'Username';
    if (lExtra2) lExtra2.textContent = 'Role';
    if (lExtra3) lExtra3.textContent = 'Password';
    if (e2) e2.placeholder = 'admin or factory';
  }
}

function parseFactoryLocation(raw) {
  const txt = (raw || '').trim();
  if (!txt) return null;
  const p = txt.split(',').map((x) => x.trim()).filter(Boolean);
  if (p.length < 2) return null;
  const lat = Number(p[0]);
  const lon = Number(p[1]);
  const radius = p.length >= 3 ? Number(p[2]) : 250;
  if (!Number.isFinite(lat) || !Number.isFinite(lon) || !Number.isFinite(radius)) return null;
  return { lat, lon, radius };
}

async function fillFactoryLocationFromGps() {
  const type = document.getElementById('masterType')?.value;
  if (type !== 'factories') {
    alert('Switch Master Type to Factories first.');
    return;
  }
  if (!navigator.geolocation) {
    alert('Browser geolocation is not available.');
    return;
  }
  navigator.geolocation.getCurrentPosition(
    (pos) => {
      const lat = pos.coords.latitude.toFixed(6);
      const lon = pos.coords.longitude.toFixed(6);
      const radius = Math.max(Math.round(pos.coords.accuracy || 250), 100);
      const e1 = document.getElementById('mExtra1');
      if (e1) e1.value = `${lat},${lon},${radius}`;
    },
    () => alert('Unable to read location. Allow location permission and try again.'),
    { enableHighAccuracy: true, timeout: 10000, maximumAge: 30000 }
  );
}
window.fillFactoryLocationFromGps = fillFactoryLocationFromGps;

function openFactoryLocationMap() {
  const parsed = parseFactoryLocation(document.getElementById('mExtra1')?.value || '');
  if (!parsed) {
    alert('Enter valid location as latitude,longitude,radius first.');
    return;
  }
  window.open(`https://maps.google.com/?q=${parsed.lat},${parsed.lon}`, '_blank');
}
window.openFactoryLocationMap = openFactoryLocationMap;

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
document.getElementById('masterType')?.addEventListener('change', updateMasterFieldHints);
updateMasterFieldHints();
loadMaster();
