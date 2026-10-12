# Roadmap and acceptance gates

| Phase | Scope | Gate |
|---|---|---|
| 0 | Environment, contracts, repository | Actual Windows/runtime capabilities inspected; boundaries documented |
| 1 | Native assistant, voice, memory, safe tools | Real model response, audio checks, responsive GUI, persistence/security tests, reproducible launch |
| 2 | Desktop context and richer control | Explicit screenshots/window access; accessibility controls; observed outcome verification |
| 3 | Coding and productivity | Scoped project inspection/edits; command allowlist; isolated checkpoints; connected sources |
| 4 | Memory and proactivity | Permission-aware retrieval; durable schedules; retention; recovery; notification controls |
| 5 | Business workflows | Separate customer/order/inventory storage; correct ledger tests; sandbox messaging; financial approvals |
| 6 | Runtime agents | Measurable advantage over single-agent workflow; budgets; checkpoints; bounded delegation |
| 7 | Remote operation | Explicit authorization/cost review; authenticated encrypted transport; no exposed desktop API |
| 8 | Release | Signed distribution/update process, fresh-machine tests, performance and accessibility review |

Phase 1 development is the current milestone. Later phases are unimplemented.
Full phase acceptance is recorded in TESTING.md rather than inferred from source
code or interface mockups. The first version uses explicit tools, not autonomous
model action planning. Cloud credentials, monetary budgets, streaming and broader
runtime autonomy require separate implementation/verification before enabling them.

