// Tooltips: placed from script, because `.ds-tip__body` is `position: fixed` so
// that a rail or header cannot clip it. Mirrors `tip.ts` in the app.
const GAP = 8;

function tipPlacement(t, pill, viewport) {
  const above = t.top - pill.height - GAP;
  const top = above >= GAP ? above : t.bottom + GAP;
  const centred = t.left + t.width / 2 - pill.width / 2;
  const rightmost = viewport.width - pill.width - GAP;
  const left = Math.max(GAP, Math.min(centred, Math.max(GAP, rightmost)));
  return { top, left };
}

let shown = null;

function hide() {
  if (shown) shown.classList.remove('is-on');
  shown = null;
}

function show(wrap) {
  const pill = wrap.querySelector('.ds-tip__body');
  if (!pill || pill === shown) return;
  hide();
  const { top, left } = tipPlacement(
    wrap.getBoundingClientRect(),
    { width: pill.offsetWidth, height: pill.offsetHeight },
    { width: window.innerWidth, height: window.innerHeight },
  );
  pill.style.top = top + 'px';
  pill.style.left = left + 'px';
  pill.classList.add('is-on');
  shown = pill;
}

function enter(e) {
  const wrap = e.target && e.target.closest && e.target.closest('.ds-tip');
  if (wrap) show(wrap);
  else if (shown) hide();
}

document.addEventListener('mouseover', enter);
document.addEventListener('focusin', enter);
document.addEventListener('mouseout', (e) => {
  const to = e.relatedTarget;
  if (!to || !to.closest || !to.closest('.ds-tip')) hide();
});
document.addEventListener('focusout', hide);
document.addEventListener('scroll', hide, true);
window.addEventListener('resize', hide);
