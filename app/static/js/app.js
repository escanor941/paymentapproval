(() => {
  const root = document.documentElement;
  const btn = document.getElementById('themeToggle');
  if (btn) {
    btn.addEventListener('click', () => {
      const current = root.getAttribute('data-bs-theme') || 'light';
      root.setAttribute('data-bs-theme', current === 'light' ? 'dark' : 'light');
    });
  }
})();
