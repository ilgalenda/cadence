# Onboarding curriculum

A generic, editable onboarding path for new Cadence users. Tailor the steps to
your own team — the Onboarding agent reads this file as grounding.

## Everyone (day one)
1. Sign in and find your agents on the Dashboard. The agents you see are set by
   your profile's `agents` list.
2. Meet **Owl** — the assistant in the drawer. Ask it anything about the
   company's knowledge; it answers from the shared vault.
3. Understand the **three-pillar knowledge vault**: Company Truth (canonical),
   Dynamic Truth (learned from calls & campaigns), Added Knowledge (admin-approved
   corrections).

## Sales / GTM track
1. **Calls Agent** — upload a call recording or paste a transcript to get a
   structured analysis (signals, objections, talking points) and a quiz.
2. **Lead Agent** — create a campaign, run an X-Ray prospect search, and generate
   outreach sequences.
3. Use **Owl in call-aware mode** from an analysed call for a deep dive.
4. Habit: after each real call, skim the extracted learnings — they compound into
   your personal knowledge layer.

## Operations track
1. **Platform shape** — every capability is an agent under `backend/agents/`;
   mutable data lives under `DATA_ROOT`, never in the repo.
2. **Duty & Tax agent** — estimate landed cost (duty + VAT/GST) for a shipment,
   either by describing it or entering figures.
3. **Forecasting agent** — review pipeline by vertical, the weighted forecast, and
   pipeline-hygiene flags (sync from your CRM first).
4. **Adding capability** — new agents are scaffolded with
   `python backend/scripts/create_agent.py`.

## Where to get unstuck
- Ask Owl first. If Owl is wrong, correct it inline — the correction goes to an
  admin for review and, once approved, becomes part of the shared knowledge.
