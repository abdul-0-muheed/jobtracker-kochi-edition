/**
 * timeline.js — Expand/collapse timeline entries on company detail page.
 */

document.querySelectorAll('.timeline-item').forEach(item => {
  const detail = item.querySelector('.timeline-detail');
  if (!detail || detail.textContent.trim().length === 0) return;

  // Initially collapse long details
  if (detail.textContent.trim().length > 80) {
    detail.style.maxHeight = '0';
    detail.style.overflow  = 'hidden';
    detail.style.transition = 'max-height 0.25s ease';

    const toggle = document.createElement('button');
    toggle.className = 'btn btn-xs btn-link text-muted p-0 mt-1';
    toggle.textContent = '▸ Show details';
    toggle.dataset.expanded = 'false';

    toggle.addEventListener('click', () => {
      const expanded = toggle.dataset.expanded === 'true';
      if (expanded) {
        detail.style.maxHeight = '0';
        toggle.textContent = '▸ Show details';
        toggle.dataset.expanded = 'false';
      } else {
        detail.style.maxHeight = detail.scrollHeight + 'px';
        toggle.textContent = '▾ Hide details';
        toggle.dataset.expanded = 'true';
      }
    });

    item.querySelector('.timeline-content').appendChild(toggle);
  }
});
