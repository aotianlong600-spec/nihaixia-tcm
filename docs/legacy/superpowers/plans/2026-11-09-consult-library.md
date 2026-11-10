# Consultation library integration plan

**Goal:** Use the existing Ni-centered source extracts and private book pack in the public browser consultation flow.

**Architecture:** Reuse the shared Python core for current facts, source retrieval, candidate ranking, frozen references and executable decision packages. Ship identified extracts with the web build. Install complete source packages into browser-local encrypted storage, with immutable original assets separated from frequently saved case snapshots.

**Tech stack:** Vue 3, Pyodide, SQLite, IndexedDB and AES-GCM.

- [x] Locate the latest local implementation at private branch feat/library-web, commit b37763d.
- [x] Port formula evidence, composition versions, signs and modification extracts without overwriting the public model integration.
- [x] Keep negation, unknown, conflict, historical and other-person facts distinct in the consultation context.
- [x] Freeze extracted quotations and validate their source identities when model results are saved or replayed.
- [x] Display analysis in the consultation flow, with explicit current-fact confirmation and independent composition versions.
- [x] Implement safe knowledge ZIP import and separately encrypted originals, retaining cases and model settings across failures and reloads.
- [x] Run the local source checks and a clean-source suite without private original files.
- [x] Verify the normal browser UI with the real private pack and synthetic model responses.
- [ ] Verify public deployment and provide the private import package.

Existing executable source packages remain the authority for applying structured modification conditions. Newly extracted modification sentences participate as source-linked retrieval material until their complete triggers and actions are represented in the decision package format.
