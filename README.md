# Module 1 — Data Collection & Preprocessing

## What's here

```
govscheme_bot/
├── schema.py                          # Pydantic models: Scheme, EligibilityCriteria
├── scrapers/
│   ├── base_scraper.py                # Abstract base: fetch/parse contract
│   └── myscheme_scraper.py            # Concrete scraper + regex-assisted extraction
├── data/
│   └── sample_schemes.json            # 3 manually-annotated real schemes
├── tests/
│   ├── fixtures/sample_scheme_page.html
│   ├── test_scraper.py                # Scraper -> Scheme, offline via fixture
│   └── test_sample_data.py            # Validates data/sample_schemes.json
└── requirements.txt
```

## Run it

```bash
pip install -r requirements.txt
python3 tests/test_sample_data.py   # validates the hand-annotated dataset
python3 tests/test_scraper.py       # runs the scraper against a local fixture
```

Both run offline — no network calls, which matters since your dev
sandbox / CI likely can't reach government sites anyway. `scrape()`
on `BaseSchemeScraper` is the one method that hits the network live.

## Design decisions worth remembering for your report/viva

1. **`None` means "unrestricted", not "unknown".** In
   `EligibilityCriteria`, a `None` field always evaluates to PASS in
   the rule engine — it's not a "missing info, ask the user" signal.
   That distinction has to be baked into the schema now, because the
   rule engine (Module 3) depends on it.

2. **`additional_conditions` exists because real schemes don't reduce
   to age/income/state.** PM-KISAN's actual exclusions (institutional
   landholders, income-tax payers) and PM-JAY's SECC-2011-based
   eligibility aren't clean numeric thresholds. Don't force them into
   fields that don't fit — surface them as text the rule engine flags
   for manual review, and the explanation-generation LLM can present
   verbatim.

3. **JS-rendered sites need a different fetch strategy.** myscheme.gov.in
   itself is React-rendered — plain `requests.get()` often won't see
   the content. `myscheme_scraper.py` documents this: either find the
   underlying JSON API via browser devtools (Network tab), or render
   with Playwright/Selenium first and feed the resulting HTML into
   `parse_html()`. The parser and fetcher are deliberately decoupled
   for exactly this reason.

4. **`verified_by` and `last_verified` exist for the versioning
   requirement** in the project plan ("government schemes change; log
   when criteria were last verified"). Regex/LLM-assisted extraction
   should be marked `"llm_assisted"` until a human has actually read
   and corrected it, at which point flip it to `"manual"`.

## Next steps (pick one)

- **Extend to more sources**: write a `state_portal_scraper.py`
  subclassing `BaseSchemeScraper` for a specific state site's actual
  markup (inspect it in browser devtools first — every gov site's
  HTML structure is different, the fixture here is illustrative only).
- **PDF ingestion**: add a `pdf_extractor.py` using `pdfplumber` for
  scheme guideline PDFs, falling back to `pytesseract` OCR for scanned
  ones — same `parse_html`-style contract, just parsing extracted text
  instead of HTML.
- **Move to Module 2**: PostgreSQL schema (`schemes`,
  `eligibility_rules` tables) that this `Scheme` model maps onto.
- **Module 3 is done** — see below.

---

# Module 3 — Rule Engine

## What's here

```
rule_engine/
├── user_profile.py   # UserProfile — structured facts known about the user
└── engine.py          # evaluate_scheme() / evaluate_all()
tests/
└── test_rule_engine.py   # 5 scenarios covering every outcome type
```

## Run it

```bash
python3 tests/test_rule_engine.py
```

## How it works

`evaluate_scheme(scheme, profile)` runs one check function per
structured `EligibilityCriteria` field (age, income, gender, caste
category, marital status, state, occupation, disability, BPL card).
Each check returns one of:

- **`None`** — the scheme doesn't restrict on this field at all; the
  condition is omitted from the results entirely (keeps output focused
  on what's actually relevant to this scheme).
- **`PASS`** — restricted, and the user's profile satisfies it.
- **`FAIL`** — restricted, and the user's profile violates it.
- **`MISSING_INFO`** — restricted, but the user hasn't provided that
  field yet.

Any `additional_conditions` text (PM-KISAN's exclusions, PM-JAY's
SECC-2011 basis, etc.) becomes a `NEEDS_REVIEW` condition — the engine
never tries to auto-evaluate free text.

The **overall status** is the worst outcome across all conditions, in
this priority order:

```
FAIL present?           -> NOT_ELIGIBLE
else MISSING_INFO?      -> PARTIALLY_ELIGIBLE   (ask the user more)
else NEEDS_REVIEW?      -> NEEDS_MANUAL_REVIEW  (can't auto-certify)
else                    -> ELIGIBLE
```

This is why PM-KISAN can never come back `ELIGIBLE` in this dataset —
its entire eligibility logic lives in `additional_conditions`, so
every profile lands at best at `NEEDS_MANUAL_REVIEW`. That's the
correct, honest behavior: the engine shouldn't claim certainty it
doesn't have.

## Design decisions worth remembering for your report/viva

1. **Per-condition results, not just a boolean.** This is what makes
   Module 6 (explanation generation) possible without hallucination —
   the LLM has a structured list of exactly which conditions passed,
   failed, or were unknown, and just needs to phrase it.
2. **`MISSING_INFO` vs `FAIL` is the whole point of the clarifying-
   question loop** (Phase 4/5 in the project plan). `PARTIALLY_ELIGIBLE`
   is the signal LangGraph's `clarify_node` should watch for — pull
   `result.missing_fields` and ask the user specifically about those.
3. **`NEEDS_MANUAL_REVIEW` is a distinct, honest outcome** — not
   folded into ELIGIBLE or PARTIALLY_ELIGIBLE. Schemes like PM-KISAN
   and PM-JAY, whose real-world eligibility isn't reducible to
   thresholds, should never come back as a confident ELIGIBLE. This
   is worth calling out explicitly in your evaluation/limitations
   section (Phase 9/10).
4. **Priority order is deliberate**: a hard FAIL always wins over
   missing info or unreviewed conditions, since there's no point
   asking the user more questions about a scheme they've already
   definitively failed.

## Next steps (pick one)

- **Module 2**: PostgreSQL schema for `schemes` / `eligibility_rules`.
- **Module 4 is done** — see below.
- **Module 5**: wire `evaluate_all()` into the LangGraph
  `evaluate_node`, with a `clarify_node` that loops back using
  `result.missing_fields` from `PARTIALLY_ELIGIBLE` results.
- **Module 6**: explanation generation — prompt an LLM with an
  `EligibilityResult` and get back natural-language phrasing of
  exactly what's already been decided.

---

# Module 4 — NLP Extraction Pipeline

## What's here

```
nlp_extraction/
├── lookups.py     # vocabulary: states, occupations, caste terms, etc.
└── extractor.py    # extract() and merge_profile()
tests/
└── test_nlp_extraction.py   # 7 scenarios incl. the project plan's own example
```

## Run it

```bash
python3 tests/test_nlp_extraction.py
```

No model download needed — `spacy.blank("en")` only loads a
tokenizer, not a trained NER model. That's a deliberate choice, not a
shortcut: age and income are number-plus-unit patterns regex handles
more reliably than generic NER, and every other field (gender,
marital status, caste category, state, occupation, disability, BPL) is
a fixed, enumerable vocabulary — exactly what a `PhraseMatcher` is for.
This is the "rule-based matcher" branch the project plan explicitly
calls out as the alternative to training a custom NER model (which
would need labeled training data you don't have yet).

## How it works

`extract(text) -> ExtractionResult` runs two independent extraction
strategies over the same text:

- **Regex** for `age` and `annual_income`. Income handles currency
  symbols (`Rs.`, `INR`), Indian numbering with commas, "lakh" units
  (`2 lakh` → `200000`), and monthly-to-annual conversion (`15000 per
  month` → `180000`) since scheme income criteria in the schema are
  always annual.
- **spaCy `PhraseMatcher`** for everything categorical, against the
  vocabulary lists in `lookups.py`. Gendered marital-status words
  (`widow`, `widower`) populate *both* `gender` and `marital_status` —
  worth remembering when you're deciding what to ask the user next.

`ExtractionResult.matched_spans` records exactly which substring
produced each field — useful for a "here's what I understood" UI
confirmation, and for debugging false extractions.

`merge_profile(existing, new)` does incremental slot-filling: a field
only gets overwritten if the new turn's extraction actually found
something, so a multi-turn conversation doesn't forget what the user
already said. A later correction ("actually I live in Tamil Nadu now")
naturally overwrites the earlier value since the new extraction is
non-null.

## Known limitations (be upfront about these in your report)

- **Negation isn't handled.** "I don't have a BPL card" will currently
  match `has_bpl_card = True`, because the matcher just looks for the
  phrase "BPL card" without checking for a preceding negator. This is
  a real gap worth fixing before Module 5 — a small negation-window
  check (e.g. spaCy's dependency parse, or a simple "no/not/without
  within N tokens before the match" rule) is the natural next
  improvement.
- **Vague quantities aren't extracted.** "no income" doesn't produce
  `annual_income = 0` — the regex only fires on actual numbers. Since
  a scheme's `income_max` check needs *some* number to compare against,
  the honest behavior is to leave it `None` (→ `MISSING_INFO` in the
  rule engine) rather than guess.
- **Single-value extraction only takes the first/earliest match.**
  If someone mentions two states in one sentence, only the first is
  captured. Fine for the common case, worth flagging as a known
  simplification.
- **Vocabulary is hand-curated and incomplete** (occupations especially).
  Extending `lookups.py` is the cheapest way to improve recall — no
  code changes needed elsewhere.

## Next steps (pick one)

- **Fix negation handling** before wiring this into a live chat loop.
- **Module 5 is done** — see below.
- **Module 2**: PostgreSQL schema, if not done yet.

---

# Module 5 — LangGraph Orchestration

## What's here

```
orchestration/
├── state.py         # ConversationState — the object threaded through every node
├── questions.py       # field -> natural-language clarifying question
├── nodes.py            # extract, retrieve, evaluate, clarify, finalize, explain nodes
└── graph.py             # builds/compiles the graph; submit_message() runs one turn
tests/
└── test_orchestration.py   # 4 scripted multi-turn conversations
```

## Run it

```bash
python3 tests/test_orchestration.py
```

## How it works

```
START -> extract -> retrieve -> evaluate -> (route) -> clarify -> END
                                                      -> finalize -> END
```

One `submit_message(state, text)` call = one user turn = one full pass
through the graph. `extract_node` runs Module 4's `extract()` and
`merge_profile()`s the result into the running profile. `retrieve_node`
uses the offline TF-IDF/ChromaDB retriever when the graph is built by
the Streamlit app, and falls back to every scheme when no retriever is
provided. `evaluate_node` runs Module 3's `evaluate_all()`.

The conditional edge after `evaluate` (`route_after_evaluate`) checks:
is any candidate scheme `PARTIALLY_ELIGIBLE`, and are turns remaining?
If yes → `clarify_node` picks a question; if no → `finalize_node` marks
the turn done. **`clarify_node`'s question choice**: it tallies missing
fields across only the `PARTIALLY_ELIGIBLE` results (not `NOT_ELIGIBLE`
ones — those are already decided and don't need more info even if the
engine recorded a missing field on them too) and asks about whichever
field would move the most schemes forward. Ties break on
`evaluate_all`'s stable sort order — documented and tested explicitly
in `test_multi_scheme_clarification_picks_most_impactful_field`,
rather than left as a surprise.

**The multi-turn "loop" happens across separate `submit_message()`
calls, not inside a single graph traversal.** Each call is one full
top-to-bottom pass; a clarifying question ending in `END` just means
"this turn is done, go get the user's answer." This mirrors how a real
chat UI actually works (each message is a separate request/response)
and avoids needing LangGraph's `interrupt()`/checkpointer machinery,
which would be overkill for this project's scope. `max_turns` in
`ConversationState` is the safety valve against a user who never
answers — verified by `test_max_turns_prevents_infinite_loop`.

## Design decisions worth remembering for your report/viva

1. **Only `retrieve_node` needs to change once the vector store
   exists.** `evaluate_node`, `clarify_node`, and everything else
   consume `candidate_schemes` generically — they don't know or care
   whether it came from "return everything" or real semantic search.
2. **Clarification only looks at `PARTIALLY_ELIGIBLE` results.** A
   scheme that already failed a hard condition doesn't get a follow-up
   question just because the engine happened to also flag a separate
   missing field on it — that would waste the user's time on a
   decision that's already made.
3. **Template questions, not an LLM call.** Consistent with Module 3's
   "don't let an LLM make decisions it doesn't need to make" — the
   *content* of the question (which field to ask about) is entirely
   rule-driven; only the *phrasing* would ever go through an LLM, and
   even that isn't necessary here since the field set is small and
   fixed.

## Next steps (pick one)

- **Module 2**: PostgreSQL schema — persist `ConversationState`
  profile/turns as `chat_sessions` / `chat_logs` rows.
- **RAG retrieval is done** — see below.
- **Module 6 and the Streamlit demo are done** — see below.
- **Module 7**: wrap `submit_message()` in a FastAPI `/chat` endpoint
  with session state keyed by a session ID, if you need a non-Streamlit
  frontend too.

---

# Module 6 — Explanation Generation, + Full Streamlit Demo

## What's here

```
explanation/
├── generator.py       # TemplateExplanationGenerator, LLMExplanationGenerator, anthropic_llm_call()
streamlit_app.py         # the full working chat demo, wiring every module together
tests/
├── test_explanation.py     # 8 tests: template + LLM-wiring (via a fake callable)
└── test_streamlit_app.py    # 6 tests: real UI interactions via Streamlit's AppTest
```

## Run the demo

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

Opens in your browser. Works with **zero configuration** — explanations
are generated by `TemplateExplanationGenerator`, no API key needed.

**To enable LLM-generated explanations instead:**
```bash
pip install anthropic
export ANTHROPIC_API_KEY=sk-...
streamlit run streamlit_app.py
```
The sidebar shows which mode is active. If the API call ever fails
mid-conversation, `LLMExplanationGenerator` silently falls back to the
template for that one explanation — the demo never crashes because of
a network hiccup.

## Run the tests (no API key, no browser, no server needed)

```bash
python3 tests/test_explanation.py
python3 tests/test_streamlit_app.py
```

`test_streamlit_app.py` uses Streamlit's own `AppTest` framework to
actually drive `streamlit_app.py` — simulated chat messages, button
clicks, and assertions on what would really render. This is genuine
UI testing, not just testing the modules the UI happens to call.

## How Module 6 works

Same principle as everywhere else in this project: **the LLM never
decides anything.** `ExplanationGenerator` is an interface with two
implementations:

- **`TemplateExplanationGenerator`** (default) — deterministic string
  templates per `EligibilityStatus`. This is what every test and the
  out-of-the-box demo use.
- **`LLMExplanationGenerator`** — takes a `llm_call: Callable[[str],
  str]` (dependency-injected, not a specific SDK import) and sends a
  prompt that embeds the already-computed `EligibilityResult` as
  ground truth, explicitly instructing the model not to invent or
  change any criteria. `build_prompt()` is tested directly to confirm
  the grounding facts (scheme name, decision, and the actual failing
  threshold) are present in every prompt.

**Note on the tech stack**: the project plan mentioned LangChain for
this step. This implementation calls the Anthropic SDK directly
instead — fewer moving parts for what's fundamentally one prompt-in,
text-out call. Because `LLMExplanationGenerator` only depends on a
plain `str -> str` callable, swapping in a LangChain-wrapped model
later is a small, isolated change (write a new factory function next
to `anthropic_llm_call()`) — nothing else in the codebase would need
to change.

**Testing an LLM integration without a real API key**: this is the
part worth highlighting in your report. `test_llm_generator_uses_fake_callable`
injects a plain Python function as `llm_call` and asserts on (a) the
exact prompt that was built and (b) that the response is passed
through correctly. `test_llm_generator_falls_back_on_error` injects a
callable that raises, and confirms the template fallback kicks in
instead of crashing. Both run with zero network access — the
dependency injection is what makes that possible.

## How the Streamlit demo ties every module together

| Module | File(s) | Role in the demo |
|---|---|---|
| 1 | `schema.py` | `Scheme` / `EligibilityCriteria` — the data model everything else is built on |
| 1 | `data/sample_schemes.json` | the scheme corpus the demo loads (hand-annotated, from Module 1) |
| 3 | `rule_engine/` | the actual eligible/not-eligible/etc. decision, per scheme |
| 4 | `nlp_extraction/` | turns each chat message into structured profile fields |
| 5 | `orchestration/` | the LangGraph state machine driving the whole conversation |
| 6 | `explanation/` | turns each decision into the text shown in the UI |

`streamlit_app.py` itself is thin by design — it holds no eligibility
logic of its own. It: loads schemes once (`st.cache_resource`), builds
the graph once (also cached, picking LLM vs. template mode based on
whether `ANTHROPIC_API_KEY` is set), keeps a `ConversationState` in
`st.session_state`, and calls `submit_message()` on every chat input.
Everything you can see in the UI — the clarifying questions, the
✅/❌/🟡/🔎 verdicts, the explanation text, the condition-by-condition
detail in each expander — is data already computed by Modules 3–6;
the UI layer only renders it.

## A real bug found and fixed during testing

Worth mentioning in your report as an example of why UI testing
matters: the sidebar's "what we know about you" panel initially
lagged one turn behind the actual conversation. Streamlit only
re-renders widgets that get re-executed, and the sidebar was being
drawn *before* the current turn's `submit_message()` call updated
`session_state` — so it always showed last turn's profile, not this
turn's. Fixed by calling `st.rerun()` immediately after updating
state, forcing a fresh top-to-bottom render. `test_sidebar_profile_updates_immediately_not_lagged`
in `test_streamlit_app.py` is a regression test for exactly this bug.

## Design decisions worth remembering for your report/viva

1. **Grounded generation, testable without a live API.** The
   dependency-injection pattern (`llm_call: Callable[[str], str]`) is
   the reusable idea here — it's how you'd unit-test *any* LLM
   integration without needing network access in CI or during grading.
2. **Graceful degradation everywhere.** No API key → template
   explanations. API call fails mid-session → falls back per-call, not
   per-conversation. The demo is never one flaky network request away
   from being unusable.
3. **The UI layer has zero business logic.** Every decision
   (eligible/not, what to ask next, what the explanation says) is
   computed by Modules 3–6 before `streamlit_app.py` ever sees it. If
   you ever swap Streamlit for a different frontend, none of the
   decision logic needs to change.

## Known limitations / next steps

- Only the 3 schemes from `data/sample_schemes.json` are in the demo
  — expand Module 1's dataset to see more variety.
- The negation gap noted in Module 4's limitations ("I don't have a
  BPL card") is still present — worth fixing before treating this as
  production-ready.
- No persistence — refreshing the browser loses the conversation
  (Module 2, PostgreSQL `chat_sessions`/`chat_logs`, is what would
  fix this).

---

# RAG Retrieval

## What's here

```
retrieval/
├── embeddings.py     # TfidfEmbeddingFunction — offline, no model download
├── vector_store.py    # ChromaDB wrapper: build(), query(), category/state filtering
└── retriever.py         # SchemeRetriever — the interface orchestration depends on
tests/
└── test_retrieval.py   # 8 scenarios, incl. a larger synthetic multi-domain corpus
```

`retrieve_node` in `orchestration/nodes.py` is now `make_retrieve_node(retriever)`
— pass a real `SchemeRetriever` for actual RAG, or `None` to return every
scheme for a caller that does not need semantic filtering.

## Run it

```bash
python3 tests/test_retrieval.py
```

## Why ChromaDB's own default embedding function isn't used

Verified directly during development, not assumed: ChromaDB's
built-in embedding function downloads a ~90MB ONNX MiniLM model from
an external host on first use. That download isn't reachable from
every environment — in this dev sandbox it fails outright with a
hash-mismatch error, the same class of problem as Module 1's
myscheme.gov.in JS-rendering issue. Rather than depend on that, a
custom `TfidfEmbeddingFunction` fits a classic TF-IDF vector space
directly over the scheme corpus — no download, fully offline,
deterministic, and inspectable (you can print the fitted vocabulary
and explain exactly which terms drove a match, which is worth having
for a viva). ChromaDB itself is genuinely used as the vector store —
only the embedding step is swapped out, through ChromaDB's own
pluggable `EmbeddingFunction` interface.

## Two real bugs found via testing, not just code review

1. **Non-deterministic ranking, traced to an all-zero embedding
   vector.** The first version used a single word-level TF-IDF
   vectorizer. A query like *"my crops were destroyed by flooding"*
   shares zero exact tokens with corpus text like *"crop failure"*
   ("crops" ≠ "crop" as tokens), so it embedded to an all-zero vector.
   ChromaDB's HNSW index handles near-zero-norm vectors degenerately —
   it returned what was effectively insertion-order noise, silently,
   with no error, and the ranking changed across repeated rebuilds of
   the *same* corpus and query. Caught this by deliberately testing
   for determinism (`test_ranking_is_deterministic_across_rebuilds`)
   rather than trusting a single passing run. **Fix**: combine
   word-level TF-IDF (whole-term meaning) with character n-gram
   TF-IDF (3-5 chars, word-boundary aware — tolerant of morphological
   variants like crop/crops without needing a stemmer or a downloaded
   lemmatizer model).
2. **`retrieve_node` wasn't actually retrieving anything.** The first
   wiring hardcoded `top_k=len(all_schemes)` — meaning candidate
   filtering was a no-op in production regardless of corpus size,
   pointless RAG. Caught this while writing the orchestration
   integration test. **Fix**: `top_k` is no longer set by
   `retrieve_node` at all — it's controlled by however the
   `SchemeRetriever` itself was constructed
   (`SchemeRetriever(..., default_top_k=N)`), keeping that
   responsibility out of the node entirely.

## Known limitation, documented rather than hidden

TF-IDF (even combined word + char n-gram) is lexical, not semantic.
A query like *"I lost my job and need support"* can rank a scheme
whose description happens to repeat the word "support" prominently
above the scheme that's actually the better match, because TF-IDF has
no way to know a word is being used generically in one case and
specifically in another. `test_known_limitation_generic_word_overlap`
asserts the *current* (imperfect) behavior on purpose — a future
embedding-model upgrade making that test fail is the intended signal
to update the test, not a regression.

## Design decisions worth remembering for your report/viva

1. **Query text is the full conversation so far, not just the latest
   message** (`ConversationState.conversation_text`, accumulated in
   `extract_node`). A later turn like "my income is 1 lakh" carries no
   retrievable signal on its own — retrieving against only that text
   could silently drop a scheme that matched fine on an earlier,
   fuller message.
2. **State filtering is done in Python (`filter_by_state`), not
   pushed into ChromaDB's `where` clause.** A scheme's
   `eligibility.state` is a list (central schemes have none, state
   schemes can list several) — list-membership filtering is simpler
   done client-side at this corpus size than fought into a `where`
   clause built for scalar equality. Category filtering, a genuinely
   scalar field, does use `where` directly.
3. **`SchemeRetriever` is the only thing orchestration depends on.**
   Swapping TF-IDF for a real sentence-transformer model, or ChromaDB
   for another vector DB entirely, never requires touching
   `orchestration/` — same dependency-injection pattern as Module 6's
   `ExplanationGenerator`.
4. **Retrieval only starts mattering past a handful of schemes.** With
   3 real schemes and `top_k=5`, the live demo's retrieval never
   excludes anything — that's expected and correctly documented in
   the sidebar, not a bug. `tests/test_retrieval.py` uses a larger,
   explicitly synthetic 8-scheme corpus specifically to demonstrate
   real filtering, since Module 1's hand-verified dataset is
   intentionally still small.

## Next steps (pick one)

- **Module 2**: PostgreSQL persistence.
- **Grow Module 1's dataset** past a handful of schemes to see RAG
  retrieval actually matter in the live demo, not just in tests.
- **Swap in a real embedding model** (`SentenceTransformerEmbeddingFunction`,
  sketched but commented out in `retrieval/embeddings.py`) once you
  have model-hub access — fixes the generic-word-overlap limitation
  above, at the cost of a model download.





