# Engagement Audit -- detailed check reference

| Check | Signal | Severity | Notes |
|---|---|---|---|
| No H1 | 0 `<h1>` elements | medium | |
| Multiple H1s | >1 `<h1>` elements | low | |
| Title/H1 keyword mismatch | no shared 4+ letter words | medium, low confidence | Coarse heuristic |
| Title/meta keyword mismatch | no shared 4+ letter words | low | Only checked if title/H1 already aligned |
| Thin navigation | <2 same-domain links | medium | |
| No CTA language | no CTA-pattern match in links/headings/title/meta | low | Deliberately low -- many legitimate pages have no CTA |

All keyword-overlap checks are heuristics meant to approximate "context
retention" (Appendix E of the PDF) -- they are capped at medium severity and
should be read by the orchestrating agent as a prompt to look closer, not as
a definitive verdict.
