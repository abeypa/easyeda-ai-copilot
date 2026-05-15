/**
 * Content script — injected into EasyEDA pages.
 * Adds a floating AI Copilot toggle button on the EasyEDA toolbar area.
 */

(function () {
  'use strict';

  if (document.getElementById('eai-toggle-btn')) return;

  let sidebarOpen = false;
  let sidebar = null;

  // ── Create toggle button ──────────────────────────────────────────────────
  const btn = document.createElement('button');
  btn.id = 'eai-toggle-btn';
  btn.title = 'EasyEDA AI Copilot';
  btn.innerHTML = `
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/>
    </svg>
    <span>AI</span>`;
  document.body.appendChild(btn);

  // ── Create sidebar iframe ─────────────────────────────────────────────────
  function createSidebar() {
    sidebar = document.createElement('iframe');
    sidebar.id = 'eai-sidebar';
    sidebar.src = chrome.runtime.getURL('plugin/index.html');
    sidebar.allow = 'clipboard-write';
    document.body.appendChild(sidebar);
  }

  function toggleSidebar() {
    if (!sidebar) createSidebar();

    sidebarOpen = !sidebarOpen;
    sidebar.classList.toggle('open', sidebarOpen);
    btn.classList.toggle('active', sidebarOpen);

    // Adjust EasyEDA canvas padding when sidebar opens
    const canvas = document.querySelector('#editorDiv, .main-container, #app');
    if (canvas) {
      canvas.style.transition = 'padding-right .3s ease';
      canvas.style.paddingRight = sidebarOpen ? '400px' : '';
    }
  }

  btn.addEventListener('click', toggleSidebar);

  // Close sidebar with Escape
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && sidebarOpen) toggleSidebar();
  });
})();
