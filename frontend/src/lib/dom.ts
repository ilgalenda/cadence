// Reaching for an element the page is built around.
//
// Five pages had each hand-copied `document.getElementById(id) as T`. The cast is
// the problem: a retired element becomes `null` in silence, and the failure lands
// wherever that handle is first dereferenced, which can be three functions and one
// swallowed `catch` away from the markup that actually changed.
//
// That is not hypothetical. Moving `/owl` onto the shared shell retired the
// breadcrumb separator — correctly, the trail draws its own in CSS — and left the
// page holding a handle to it. `setCrumb()` sat ahead of the empty state, the
// conversation restore and the first send, so one null took the whole surface down
// and reported it as "could not load this conversation".
//
// So the lookup fails here instead, naming the id.

/**
 * An element the calling page requires. A missing id is a defect in the markup,
 * not a state to handle, so it throws rather than returning null.
 */
export function el<T extends HTMLElement>(id: string): T {
  const found = document.getElementById(id);
  if (!found) throw new Error(`Missing required element #${id}`);
  return found as T;
}
