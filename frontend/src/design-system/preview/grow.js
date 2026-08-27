// Growing fields: native where supported, one delegated listener where not.
document.addEventListener('input', (e) => {
  const el = e.target;
  if (!(el instanceof HTMLTextAreaElement)) return;
  if (!el.matches('.ds-textarea, .ds-grow, .ds-composer__input')) return;
  if (CSS.supports('field-sizing', 'content')) return;
  el.style.height = 'auto';
  el.style.height = el.scrollHeight + 'px';
});
