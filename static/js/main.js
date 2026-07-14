/**
 * main.js — Dashboard polling, sync status, and global utilities.
 */

// ── Sync status poller ────────────────────────────────────────────────────────
let _syncPollInterval = null;

function startSyncPoll(jobId, statusEl, progressEl) {
  if (_syncPollInterval) clearInterval(_syncPollInterval);
  if (progressEl) progressEl.classList.remove('d-none');

  _syncPollInterval = setInterval(async () => {
    try {
      const res = await fetch(`/api/sync-status/${jobId}`);
      const d = await res.json();
      if (statusEl) {
        statusEl.textContent = `${d.status} — processed: ${d.items_processed || 0}, new: ${d.items_new || 0}`;
      }
      if (d.status !== 'running') {
        clearInterval(_syncPollInterval);
        if (progressEl) progressEl.classList.add('d-none');
        if (d.status === 'success') {
          showToast(`✓ Sync complete! ${d.items_new || 0} new events.`, 'success');
          setTimeout(() => location.reload(), 1500);
        } else {
          showToast(`✗ Sync ${d.status}: ${d.error || ''}`, 'danger');
        }
      }
    } catch (e) {
      clearInterval(_syncPollInterval);
    }
  }, 2000);
}

// ── Toast helper ──────────────────────────────────────────────────────────────
function showToast(message, type = 'info') {
  const container = document.querySelector('.flash-container') || document.body;
  const div = document.createElement('div');
  div.className = `alert alert-${type} alert-dismissible fade show flash-alert`;
  div.innerHTML = `${message} <button type="button" class="btn-close" data-bs-dismiss="alert"></button>`;
  container.prepend(div);
  setTimeout(() => {
    const bsAlert = bootstrap.Alert.getOrCreateInstance(div);
    bsAlert.close();
  }, 5000);
}

// ── Dashboard sync form ───────────────────────────────────────────────────────
const dashSyncForm = document.querySelector('.sync-form');
if (dashSyncForm) {
  dashSyncForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const fd = new FormData(dashSyncForm);
    const res = await fetch(dashSyncForm.action, { method: 'POST', body: fd });
    if (!res.ok) { showToast('Failed to start sync.', 'danger'); return; }
    const { job_id } = await res.json();
    showToast(`Sync started (job ${job_id}). Polling for updates…`, 'info');
    startSyncPoll(job_id, null, null);
  });
}

// ── Keyboard shortcut: / to focus search ──────────────────────────────────────
document.addEventListener('keydown', (e) => {
  if (e.key === '/' && !['INPUT','TEXTAREA'].includes(document.activeElement.tagName)) {
    e.preventDefault();
    const search = document.querySelector('input[name="q"]');
    if (search) { search.focus(); search.select(); }
  }
});
