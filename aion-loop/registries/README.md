# registries

Machine registries of the loop. One JSON record per line; every file here holds **one example record** so you can see the
schema — replace it with your own history as it accumulates (the tools append; nothing here is required to be kept).

| file | what | written by |
|---|---|---|
| `otkazy-novye.jsonl` → `failures.jsonl` | failures, 17 fields (family, real example, cause, protection, how the protection was tested, regression guard, known bad actions, safe alternative, status) | you / the executor; `bin/sobrat-otkazy.py` rebuilds `failures.jsonl` |
| `semeystva.jsonl`, `perehody-diagnostiki.ndjson` | failure families; third repeat → DIAGNOSIS_REQUIRED, patches forbidden until a hypothesis | `bin/semeystva.py` |
| `decisions.jsonl` (`istochniki/resheniya-novye.jsonl`) | owner decisions | you |
| `owner-decision-queue.jsonl` | questions to the owner (§20): written as files, never as a popup; work continues | `bin/ochered.py` |
| `zayavki/` (created on first use) | capability requests (§19) | `bin/zayavka.py` |
| `incidents.jsonl` | incidents (rollbacks, outages) | `bin/prodvizhenie.py`, you |
| `invariants.jsonl`, `sledy/` | proven behaviours with probe + cost, causal trace per DONE item | `bin/sled.py sobrat` |
| `regressii-zhurnal.ndjson` | every regression run (layers, runs, result) | `bin/regressii.py` |
| `ai-exchange-ledger.jsonl` | every exchange between agents (§23) | `bin/sobrat-reestry.py` |
| `patterns.jsonl`, `methods.jsonl` | proven patterns and how-to methods | `bin/sobrat-reestry.py` |
| `company.jsonl`, `product-manifest.jsonl` | who owns what; products and their status | you (sources in `istochniki/`) |
