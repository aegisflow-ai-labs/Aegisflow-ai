# ADR-012: Agent map as the primary workspace

Status: implemented for review

The primary browser view follows the supplied visual reference: fixed dark sidebar,
top search, dotted topology canvas, control-layer node, specialist column and source
column. AegisFlow branding and actual capability states replace the reference's
brand, invented people and third-party connection counts.

Five catalog roles are visible. Only A21's tested synthetic subset is implemented;
the remaining cards say planned. Edges connect the available A21 workflow to its
five synthetic source categories. Persisted investigations replace source previews
with escaped case snapshots. Case findings link to evidence disclosures, and delay,
SLA, recommendation and chronology are shown below the topology.

A small same-origin script supplies local search, status filtering, map/list switch,
role inspection and bounded zoom. It uses textContent for inspector content and does
not read authentication data or issue mutations. CSP allows same-origin scripts;
inline scripts, third-party scripts and external data requests remain blocked.
Keyboard controls, visible focus and stacked mobile layout are retained.

Validation covers source escaping, capability boundaries, controls, evidence
disclosure, all five scenario outcomes, login, session revocation and logout.
