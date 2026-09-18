# Ambiguous locator matches, as they are found

A citation with a locator (`\cite[Theorem 9.4]{key}`) is meant to name one result of the cited work. Sometimes it names several, or names a part of a multi-part postnote that resolves while the rest does not. We do not yet know what those cases look like in real papers, so weft does not guess at them: **an ambiguous match records no edge**, and the case is logged here with its evidence.

The decision — record every match with a confidence, record none, or record the best one marked uncertain — waits until this file holds enough cases to decide from. A wrong dependency is worse than a missing one while an agent is reasoning over the graph, which is why the safe behaviour is the one in place meanwhile.

## What is logged

One row per occurrence, appended by the linker:

| field | meaning |
|---|---|
| when | the run that found it |
| citing | the result whose text carries the citation, as a URI key |
| cited work | the work the citekey resolved to |
| postnote | the locator exactly as printed |
| normalised | the locator after §6 of the digest contract |
| matched | every result key the locator matched, with the match form that matched it |
| kind | `several` (more than one result answered), `partial` (some parts of a multi-part postnote resolved and others did not), or `none-but-close` (nothing matched and something nearly did) |

## Occurrences

_None yet: the linker lands in M3._
