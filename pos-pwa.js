/* Installation UI; sales and offline storage remain owned by offline-pos.js. */
(() => {
  const button = document.getElementById('installPosButton');
  const dialog = document.getElementById('installPosDialog');
  const standalone = matchMedia('(display-mode: standalone)');
  let promptEvent = null, locationReady = false, manifestUrl = "";
  const installed = () => standalone.matches || navigator.standalone === true;
  const refresh = () => { button.hidden = installed() || !locationReady; };
  function configure(session, branch) {
    if (!branch) return;
    const label = [branch.name, branch.address].filter(Boolean).join(' · ');
    const url = '/api/v1/pos/manifest.webmanifest?' + new URLSearchParams({location:session.branchId, tenant:session.tenantSlug || ''});
    if (url !== manifestUrl) {
      promptEvent = null; manifestUrl = url;
      document.getElementById('posManifest').href = url;
    }
    locationReady = true;
    document.title = `Oimo POS · ${label}`;
    button.textContent = `Установить кассу · ${label}`;
    document.getElementById('installPosLocation').textContent = label;
    refresh();
  }
  window.OimoPwa = {configure};
  if (typeof currentSession !== 'undefined' && typeof workspaceState !== 'undefined' && currentSession && workspaceState) {
    configure(currentSession, (workspaceState.branches || []).find(row => String(row.id) === String(currentSession.branchId)));
  }
  refresh();
  standalone.addEventListener('change', refresh);
  addEventListener('beforeinstallprompt', event => {
    event.preventDefault(); promptEvent = event; refresh();
  });
  addEventListener('appinstalled', () => {
    promptEvent = null; button.hidden = true;
    if (dialog.open) dialog.close();
  });
  button.addEventListener('click', async () => {
    if (!promptEvent) { dialog.showModal(); return; }
    const event = promptEvent; promptEvent = null; button.disabled = true;
    try { await event.prompt(); await event.userChoice; }
    catch { dialog.showModal(); }
    finally { button.disabled = false; }
  });
  document.getElementById('closeInstallPos').addEventListener('click', () => dialog.close());
  // Register on the POS page even before a cashier signs in.
  if (isSecureContext && 'serviceWorker' in navigator && location.pathname === '/pos') {
    navigator.serviceWorker.register('/pos-worker.js', {scope:'/pos'}).catch(() => {});
  }
})();
