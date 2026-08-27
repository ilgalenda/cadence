# Duty & Tax Agent

> **Operations — part two.**
> A v1 agent, kept deliberately. It predates the Owl Mind and still calls the
> retired `agents.shared.anthropic_client` directly, so it is not registered in
> `backend/main.py` and does not run in this build. Bringing these onto the Mind
> is the next section of work; see [Operations](../operations.md).


Autonomous shipment landed-cost estimation for operations teams. Describe a
shipment in plain language and the agent classifies the HS code, looks up
duty/VAT rates, and computes the breakdown via a tool-use loop — or enter the
figures directly for a deterministic quote. The maths and the rates are always
deterministic local functions; the model only orchestrates and explains.

Router prefix: `/api/duty` (gated by `require_agent_access("duty")`).
Backend: `backend/agents/duty/`.

## How it works

- **Structured quote** (`/quote`): given destination, HS code, and values, it
  looks up rates and calls the engine directly — fully deterministic.
- **Assist** (`/assist`): given a free-text shipment, the model runs a bounded
  (≤6 iteration) tool-use loop, streaming its reasoning:
  1. infers the HS code from the description,
  2. calls `lookup_duty_rate(destination, hs_code)`,
  3. calls `compute_landed_cost(...)`,
  4. explains the result.
- Quotes are saved to the user's history.

## Endpoints

Gated by `require_agent_access("duty")`.

| Method · Path | Type | Description |
|---|---|---|
| `POST /api/duty/quote` | JSON | Deterministic landed-cost from structured input |
| `POST /api/duty/assist` | SSE | Free-text shipment → autonomous quote (tool-use) |
| `GET /api/duty/quotes` | JSON | The user's saved quotes |
| `GET /api/duty/stats` | JSON | Quote count |

## Logic

- **`calc.py`** — `compute_landed_cost(goods_value, freight, insurance,
  other_fees, duty_rate, vat_rate, valuation_basis, currency)` returns an itemised
  breakdown (`dutiable_value`, `duty`, `vat_base`, `vat`, `total_taxes`,
  `landed_cost`). Duty is charged on the dutiable value (CIF = goods + freight +
  insurance; FOB = goods only); VAT/GST on the full landed value plus duty.
- **`rates.py`** — the `DutyRateProvider` interface. `MockDutyRateProvider` ships a
  generic sample table (≈10 destinations × HS chapters → duty% + VAT% +
  valuation basis). Swap the implementation in `get_provider()` for a real
  tariff/customs API to go live.
- **Tools** (`routes.py`): `lookup_duty_rate` and `compute_landed_cost`, both
  thin wrappers over the deterministic functions. Model: `claude-sonnet-4-6`;
  system prompt `DUTY_SYSTEM` in `prompts.py`.

## Data & storage

`quotes` collection (per-user, sandbox-aware, cap 200) at
`${DATA_ROOT}/agents/duty/data/quotes.json`. Each record stores the inputs, the
looked-up `rate`, and the computed `breakdown`.

## Frontend

`frontend/src/pages/agents/duty/` — Overview (recent quotes) and New quote (a
"Describe it" assist mode reusing `streamChat`, and a "Structured" calculator).

## Tests

`backend/tests/test_duty.py` — CIF/FOB breakdown maths, zero-rate, input
validation, and the mock provider's known/default lookups.

## Key files

- `routes.py` — endpoints + tool-use loop · `calc.py` — landed-cost engine ·
  `rates.py` — rate provider interface + mock · `prompts.py` — system prompt ·
  `storage.py` — quotes collection.

> Figures come from sample rate data and are estimates, not customs advice.
