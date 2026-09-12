| Check | Signal | Severity floor/ceiling | Notes |
|---|---|---|---|
| robots.txt disallow | `can_fetch()` False | critical | Only if robots.txt was actually readable |
| Named AI crawlers disallow | `rp.can_fetch(agent, url)` False | critical / high | Cites exact matched line for GPTBot/ClaudeBot/PerplexityBot/Google-Extended |
| robots.txt unreadable | fetch error | (no finding) | Reported as unknown, not disallow |
| Fetch failure | transport error / no response | critical | Stops content checks |
| HTTP >=500 | status code | critical | |
| HTTP 400-499 | status code | high | |
| JS-render dependency | visible_text < 200 chars AND (script_ratio >= 0.85 OR empty framework root) | high | Requires BOTH thinness and a JS signal |
| Thin content (no JS signal) | visible_text < 200 chars | medium | |
| No JSON-LD | 0 ld+json blocks | medium | Never critical/high alone |
| Invalid JSON-LD | parse error on >=1 block | medium | |
| Missing title | empty `<title>` | high | |
| Missing meta description | no `name="description"` | low | |
| No canonical | no `rel="canonical"` | low | |
| Declared sitemap broken | 4xx/5xx on declared sitemap URL | medium | Validates robots.txt declared sitemaps (first 3) |
| No sitemap.xml | 4xx/5xx on `/sitemap.xml` | low | Fallback when no sitemap declared |
| No /llms.txt | 404 on `/llms.txt` | low | Proactive AI optimization suggestion |
| Broken internal links | any 4xx/5xx among sampled (<=15) same-domain links | medium | Reports sample of failures |


Rationale for each threshold is in Appendix A-C of the Round 3 PDF: crawl
access, then readability, then fact extractability are treated as sequential
gates -- a failure earlier in the chain is generally more severe than one
later in it, because it blocks everything downstream.
