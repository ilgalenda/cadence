# The design system — "the studio"

Cadence runs on one design system, rebuilt 2026-08-19 and ratified 2026-08-20.
It is not a component library bolted onto the app; it is the reason 26 pages
look like one product.

`frontend/src/design-system/tokens.css` is the source of truth for colour, type,
space, radius and motion. A build gate fails on raw `px` anywhere in the app, so
a value that is not in the system cannot quietly appear in a page.

> The screenshots below are captured from the design system's own preview pages
> (`frontend/src/design-system/preview/`), not from the running product. They are
> the specification rendering itself. Names and figures in them are fictional.

---

## The position

**A calm, white, unhurried field.** White ground, soft grey wells, pill geometry,
generous air — and charcoal spent only where the user commits. The interface
earns credibility by being quiet, so the moments that are not quiet mean
something.

Nine consequences follow from that, and one is load-bearing enough to state here:
**glass survives on the floating layer only** — menus, dialogs, toasts, tooltips,
the palette, the drawer. Everything structural is solid. Never glass on glass.

---

## Screens

The shell, and three surfaces built in it.

![The shell](images/screen-shell.png)
*The one valid construction: white field, slim rail, hairline separation.*

![Cadence home](images/screen-cadence-home.png)
*What opens when Cadence launches — Owl, empty, ready.*

![Owl workspace](images/screen-owl-workspace.png)
*A conversation in flight: bubble question, prose answer, citations back to canon, an agent picked up mid-thread.*

![X-ray results](images/screen-xray.png)
*An agent page: ask in the column, a grouped people table, an index of what was kept.*

![Rail closed](images/screen-cadence-home-closed.png)
*The same home screen with the rail reduced to icons.*

![Portal card](images/portal-cadence-card.png)
*The Cadence entry tile: lockup and one line.*

---

## Foundations

![Colour](images/foundations-colour.png)
*The palette given interface roles. The system speaks in sync language — locked, drift, fault — so a colour states a condition rather than a mood.*

![Typography](images/foundations-type.png)
*Big bold headlines, calm body, mono as a whisper.*

![Material and depth](images/foundations-material.png)
*Glass on the floating layer only; soft diffuse elevation.*

![Motion](images/foundations-motion.png)
*Spring-based, interruptible, and reduced-motion aware.*

![Icons](images/foundations-icons.png)

![App marks](images/foundations-app-marks.png)

![Brand](images/foundations-brand.png)

![Series](images/foundations-series.png)

---

## Components

![Chat](images/components-chat.png)
*Bubble question, prose answer, a quiet machine readout between.*

![Controls](images/components-controls.png)

![Data](images/components-data.png)

![Forms](images/components-forms.png)

![Feedback](images/components-feedback.png)

---

## Regenerating these

The previews are static HTML with no backend. Serve
`frontend/src/design-system/` over HTTP and open `preview/`; each page carries a
`@dsCard` comment naming its group and intended viewport.
