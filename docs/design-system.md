# The design system

Cadence runs on one design system, rebuilt in August 2026 and settled shortly
after. It is not a component library bolted onto the app. It is the reason 26
pages still look like one product.

## Why it looks like this

The direction is minimal Scandinavian: plain, quiet, and with the complexity kept
out of the way.

That was a decision about adoption rather than taste. An internal platform lives
or dies in its first fortnight. If a sales team finds the tool itself effortful,
they go back to a spreadsheet and the whole thing was wasted, however good the
agents underneath are. So the interface had to ask for almost nothing: no
learning curve worth the name, no visual noise competing with the work, and
nothing that makes someone hesitate before clicking.

The second constraint was endurance. People sit in this for hours at a stretch,
reading transcripts and drafts. A screen that shouts loses that person by mid
afternoon. Everything below follows from those two things.

This came out of trial and error rather than training. What worked, in the end,
was restraint: a white field, soft geometric forms, generous space, and colour
used sparingly enough that it means something when it appears.

## The rules that hold it together

**One background, measured once.** The field is plain white everywhere. The
translucent rails and gradient grounds of the earlier version are gone. Every
contrast figure in the previews is measured against it rather than estimated.

**Glass only on things that float.** Menus, dialogs, toasts, tooltips, the
command palette, the drawer. Everything structural is solid, and glass never sits
on glass. Depth is a signal that something is temporary and sits above the page,
so spending it on permanent furniture would say nothing.

**Charcoal is an accent, not a frame.** It marks the moment a user commits: the
primary button, the bulk bar, a toast. A whole pane in charcoal is a mistake.

**Colour states a condition.** The palette speaks in the language of the domain,
which for a timing platform means locked, drift and fault. A colour says what is
true, not what mood the screen is in. Gold has exactly one meaning, canonical
knowledge, and appears nowhere else.

**No literal values in the app.** `tokens.css` holds every colour, size, radius
and timing value. A build step fails on a raw pixel value anywhere outside the
design system itself, which is the only reason the pages still match each other
after a year of changes.

## Screens

The shell, and three surfaces built inside it.

> The screenshots below are captured from the design system's own preview pages
> in `frontend/src/design-system/preview/`, not from the running platform. They
> are the specification rendering itself, and the names and figures in them are
> invented.

![The shell](images/screen-shell.png)
*White field, slim rail, hairline separation. The one valid construction.*

![Cadence home](images/screen-cadence-home.png)
*What opens when Cadence launches. Owl, empty, ready.*

![Owl workspace](images/screen-owl-workspace.png)
*A conversation in flight: a question, a prose answer, citations back to canon, and an agent picked up mid thread.*

![X-ray results](images/screen-xray.png)
*An agent page. Ask in the column, read a grouped table of people, and see an index of what was kept.*

![Rail closed](images/screen-cadence-home-closed.png)
*The same home screen with the rail reduced to icons.*

![Portal card](images/portal-cadence-card.png)
*The Cadence entry tile: lockup and one line.*

## Foundations

![Colour](images/foundations-colour.png)
*The palette with interface roles attached, and every contrast ratio measured against the white field.*

![Typography](images/foundations-type.png)
*Big bold headlines, calm body copy, monospace kept to a whisper.*

![Material and depth](images/foundations-material.png)
*Glass on the floating layer only, and soft diffuse elevation everywhere else.*

![Motion](images/foundations-motion.png)
*Spring based, interruptible, and aware of reduced motion preferences.*

![Icons](images/foundations-icons.png)

![App marks](images/foundations-app-marks.png)

![Brand](images/foundations-brand.png)

![Series](images/foundations-series.png)

## Components

![Chat](images/components-chat.png)
*A bubble question, a prose answer, and a quiet machine readout between them.*

![Controls](images/components-controls.png)

![Data](images/components-data.png)

![Forms](images/components-forms.png)

![Feedback](images/components-feedback.png)

## Looking at these yourself

The previews are static HTML with no backend. Serve
`frontend/src/design-system/` over HTTP and open `preview/`. Each page carries a
`@dsCard` comment naming its group and the viewport it was designed for.
