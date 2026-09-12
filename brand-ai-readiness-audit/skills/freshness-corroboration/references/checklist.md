# Freshness/Corroboration -- detailed check reference

| Check | Signal | Severity | Notes |
|---|---|---|---|
| No freshness signal | no Last-Modified, date meta, or JSON-LD date fields | medium | Absence of a signal, not proof of staleness |
| Stale signal | most recent date > 365 days old | medium | |
| Very stale signal | most recent date > ~730 days old | high | |
| sameAs authority links missing | Organization JSON-LD lacks `sameAs` array | low | Appendix D: anchors entity identity |
| Entity name ambiguity | >=2 distinct name strings across title/H1/JSON-LD `name` | low-medium | Soft signal; not an identity verdict |

| facts_to_corroborate | entity name, foundingDate, address, telephone found in JSON-LD | n/a (evidence only) | Consumed by orchestrator's agent-level web_search step |

This skill never calls out to other domains itself -- see the module
docstring in `scripts/freshness_check.py` for why corroboration is kept as
an explicit agent-level step rather than scripted.
