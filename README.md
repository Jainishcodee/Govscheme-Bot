# Government Scheme Eligibility Chatbot

## 1. Project Overview

This project is a chatbot that helps a user discover government schemes for
which they may qualify. The user does not need to fill a long form. They can
write a normal sentence such as:

```text
I am 65 years old, live in Gujarat, and my annual income is around 1 lakh.
```

The application performs the following work:

1. Extracts facts from the user's message.
2. Stores those facts in a structured user profile.
3. Compares the profile with the eligibility criteria of each scheme.
4. Asks a follow-up question when an important fact is missing.
5. Produces an eligibility result for every candidate scheme.
6. Explains each result in simple language.

The most important design principle is separation of responsibility:

- The deterministic rule engine makes eligibility decisions.
- NLP extracts facts from the user's text.
- LangGraph controls the conversation flow.
- The explanation generator only explains an existing decision.
- Streamlit displays the conversation and results.

An LLM is never trusted to make the eligibility decision directly.

## 2. Repository Structure

```text
govscheme_bot/
|-- schema.py
|-- requirements.txt
|-- streamlit_app.py
|-- data/
|   `-- sample_schemes.json
|-- scrapers/
|   |-- base_scraper.py
|   `-- myscheme_scraper.py
|-- rule_engine/
|   |-- __init__.py
|   |-- user_profile.py
|   `-- engine.py
|-- nlp_extraction/
|   |-- __init__.py
|   |-- lookups.py
|   `-- extractor.py
|-- orchestration/
|   |-- __init__.py
|   |-- state.py
|   |-- questions.py
|   |-- nodes.py
|   `-- graph.py
|-- explanation/
|   |-- __init__.py
|   `-- generator.py
|-- tests/
|   |-- fixtures/sample_scheme_page.html
|   |-- test_sample_data.py
|   |-- test_scraper.py
|   |-- test_rule_engine.py
|   |-- test_nlp_extraction.py
|   |-- test_orchestration.py
|   |-- test_explanation.py
|   `-- test_streamlit_app.py
```

## 3. End-to-End Working

The complete request flow is:

```text
User message
    |
    v
Streamlit chat input
    |
    v
submit_message()
    |
    v
extract_node: text -> UserProfile
    |
    v
retrieve_node: choose candidate schemes
    |
    v
evaluate_node: apply deterministic rules
    |
    +--> missing information -> clarify_node -> ask question
    |
    `--> enough information -> finalize_node -> explanations
                                            |
                                            v
                                      Streamlit results
```

One call to `submit_message()` processes one user turn. A clarification
question ends that turn. The user's answer is processed by a later call with
the same conversation state.

## 4. Module 1: Schema and Scheme Data

### Files

- `schema.py`
- `data/sample_schemes.json`

### Purpose

The schema defines the shape and meaning of all scheme and user eligibility
data. Pydantic validates values when objects are created, which prevents
malformed scheme records from silently entering the application.

### `EligibilityCriteria`

This model contains structured conditions such as:

```text
age_min, age_max
income_min, income_max
gender
caste_category
marital_status
state
occupation
disability_status
bpl_required
additional_conditions
```

`None` has a specific meaning: the scheme has no restriction on that field.
For example, `age_min=None` means that age is unrestricted. It does not mean
that the application forgot to collect the age.

The model also validates that `age_max` is not smaller than `age_min` and that
`income_max` is not smaller than `income_min`.

### `Scheme`

The `Scheme` model stores:

- Stable identifier and name.
- Description, department, and category.
- Structured eligibility criteria.
- Benefits and required documents.
- Application and source URLs.
- Verification date and verification method.

The sample JSON contains three schemes: PM-KISAN, PM-JAY, and Vay Vandana
Pension Yojana for Gujarat.

## 5. Module 2: Data Collection and Scraping

### Files

- `scrapers/base_scraper.py`
- `scrapers/myscheme_scraper.py`
- `tests/fixtures/sample_scheme_page.html`

### `BaseSchemeScraper`

The base class defines a common contract for source-specific scrapers:

```python
fetch_html(url) -> str
parse_html(html, source_url) -> Scheme
scrape(url) -> Scheme
scrape_from_file(html_path, source_url) -> Scheme
```

Fetching and parsing are deliberately separate. `scrape()` is used for live
network access, while `scrape_from_file()` allows repeatable offline tests.
Network failures are converted into `ScraperError`, so a calling pipeline can
handle a bad page without crashing the entire run.

### `MySchemeStyleScraper`

The concrete scraper reads HTML elements using CSS selectors:

- `.scheme-title`
- `.scheme-department`
- `.scheme-category`
- `.scheme-description p`
- `.eligibility li`
- `.benefits p`
- `.documents li`
- `.apply-link`

It uses BeautifulSoup for HTML parsing and regular expressions for simple
numeric extraction. For example:

```text
Applicants aged 60 years or above.
Annual income must not exceed Rs. 150,000.
```

becomes:

```text
age_min = 60
income_max = 150000
```

The parser then constructs a validated `Scheme` object. The local fixture
tests this process without making a network request.

### Important scraping limitation

Some real government portals render content using JavaScript. A normal
`requests.get()` call may return only an HTML shell. In production, the
application would need either the site's underlying JSON API or a rendered
page from Playwright or Selenium before calling `parse_html()`.

## 6. Module 3: Deterministic Rule Engine

### Files

- `rule_engine/user_profile.py`
- `rule_engine/engine.py`

### User profile

`UserProfile` represents facts known about the user:

```python
UserProfile(
    age=65,
    annual_income=100000,
    state="gujarat",
    gender="female",
)
```

Every profile field is optional because information is collected over several
conversation turns.

### `evaluate_scheme()`

The function compares one `Scheme` with one `UserProfile`. It runs an
individual checker for age, income, gender, caste, marital status, state,
occupation, disability, and BPL status.

Each checker returns one of these statuses:

- `PASS`: the user satisfies the condition.
- `FAIL`: the user violates the condition.
- `MISSING_INFO`: the scheme has a condition, but the profile lacks the value.
- `NEEDS_REVIEW`: the condition is free text and cannot be safely evaluated.

Conditions that do not restrict a scheme are omitted from the result. This
keeps the output focused on relevant rules.

### Overall status

The engine combines individual condition results using this priority:

```text
Any FAIL          -> NOT_ELIGIBLE
Otherwise missing -> PARTIALLY_ELIGIBLE
Otherwise review  -> NEEDS_MANUAL_REVIEW
Otherwise         -> ELIGIBLE
```

The priority matters. A definite failure wins over missing information because
asking more questions cannot change a scheme that the user already failed.

Free-text conditions are never guessed. For example, PM-KISAN may contain
conditions about institutional landholders or income-tax payers. The engine
marks those conditions for manual review instead of making an unsafe claim.

### `evaluate_all()`

`evaluate_all()` evaluates every candidate scheme and sorts the results by
status. The returned `EligibilityResult` includes the scheme name, overall
status, every checked condition, failed conditions, and missing fields.

## 7. Module 4: NLP Extraction Pipeline

### Files

- `nlp_extraction/lookups.py`
- `nlp_extraction/extractor.py`

### Purpose

This module converts natural language into a `UserProfile`. It does not decide
eligibility.

### Numeric extraction with regular expressions

Regular expressions extract values that have predictable numeric patterns:

```text
62-year-old              -> age = 62
aged 60                  -> age = 60
2 lakh                   -> annual_income = 200000
Rs. 1,50,000             -> annual_income = 150000
15000 per month          -> annual_income = 180000
```

Monthly income is multiplied by twelve because the scheme schema stores
annual income.

### Categorical extraction with spaCy PhraseMatcher

The extractor uses a blank spaCy English pipeline and a `PhraseMatcher`. No
large language model or pretrained NER model is downloaded. The matcher reads
vocabularies from `lookups.py` for:

- Indian states.
- Occupations.
- Caste categories.
- Marital statuses.
- Gender terms.
- Disability terms.
- BPL terms.

Values are normalized so that, for example, `Gujarat` becomes `gujarat` and
`farming` becomes `farmer`.

Gendered marital terms provide two facts. The word `widow` produces both
`gender=female` and `marital_status=widowed`.

### Matched spans

`ExtractionResult.matched_spans` records the exact text that produced each
field. This supports debugging and lets a future interface show the user what
the application understood.

### Incremental merging

`merge_profile(existing, new)` updates only fields found in the new message.
Existing values are preserved when the new message does not mention them.
This enables multi-turn slot filling:

```text
Turn 1: I am 65 and live in Gujarat.
        age=65, state=gujarat

Turn 2: My annual income is 1 lakh.
        age=65, state=gujarat, annual_income=100000
```

### Current extraction limitation

Negation is not fully handled. A sentence such as `I do not have a BPL card`
may still match the phrase `BPL card`. This must be fixed before relying on
the extractor for production decisions.

## 8. Module 5: LangGraph Orchestration

### Files

- `orchestration/state.py`
- `orchestration/questions.py`
- `orchestration/nodes.py`
- `orchestration/graph.py`

### Conversation state

`ConversationState` is the object passed through every graph node. It stores:

- The current user message.
- The accumulated `UserProfile`.
- Current turn count and maximum turns.
- All loaded schemes.
- Candidate schemes.
- Eligibility results.
- Generated explanations.
- Clarification status and question.
- Whether the conversation is finished.

### Graph nodes

#### `extract_node`

Calls `extract()` on the current message and merges the extracted profile into
the existing profile. It also increments the turn count.

#### `retrieve_node`

Currently returns every loaded scheme. This is an intentional retrieval stub
because the sample corpus is very small. A future ChromaDB or vector-search
implementation can replace this node without changing the downstream rule
engine or UI.

#### `evaluate_node`

Calls `evaluate_all()` for the candidate schemes and stores the results.

#### `route_after_evaluate`

Chooses whether to ask a question or finish the turn:

- If a candidate is partially eligible and turns remain, route to `clarify`.
- Otherwise, route to `finalize`.

#### `clarify_node`

Counts missing fields across only the `PARTIALLY_ELIGIBLE` results. It asks
about the field that can move the greatest number of schemes forward. A failed
scheme is excluded from this calculation because it already has a definite
negative result.

#### `finalize_node`

Marks the state as complete and generates one explanation per result.

### Why the loop is across messages

The graph processes one message at a time. A clarification question ends the
current graph execution. When the user answers, the application invokes the
graph again with the updated state. This matches how a real chat application
works and avoids unnecessary checkpointing complexity.

## 9. Module 6: Explanation Generation

### File

- `explanation/generator.py`

### Template explanation

`TemplateExplanationGenerator` is the default. It is deterministic, works
offline, and creates text based on the existing `EligibilityResult`.

It handles all four outcomes:

- Eligible: lists passed conditions.
- Not eligible: lists failed conditions.
- Partially eligible: lists information still needed.
- Needs manual review: lists conditions that require human verification.

### LLM explanation

`LLMExplanationGenerator` accepts a dependency-injected callable:

```python
llm_call: Callable[[str], str]
```

The prompt includes the scheme name, decision, condition statuses, and exact
values. It tells the model not to invent or change any rule. The model only
rephrases the deterministic result.

The Anthropic factory is optional and is imported only when called. If the API
key is absent, the application uses templates. If an API call fails, the
generator falls back to the template explanation for that result.

This design makes the LLM integration testable without an API key: the tests
inject a fake callable and verify both the prompt and returned text.

## 10. Module 7: Streamlit Application

### File

- `streamlit_app.py`

The Streamlit application is the user-facing layer. It contains no eligibility
logic of its own.

On startup it:

1. Loads and validates `data/sample_schemes.json`.
2. Creates a conversation state.
3. Builds the LangGraph once.
4. Selects template explanations by default, or LLM explanations when an
   Anthropic API key is configured.

For each chat message it:

1. Adds the user message to chat history.
2. Calls `submit_message()`.
3. Displays a clarification question if one is needed.
4. Displays result explanations when the conversation is complete.
5. Shows the current extracted profile in the sidebar.

The application uses Streamlit session state so the conversation survives
normal reruns during the current browser session. The current implementation
does not persist state to a database.

## 11. Running the Project

Create or activate the project virtual environment, then install dependencies:

```powershell
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Run the Streamlit application:

```powershell
streamlit run streamlit_app.py
```

Open the URL shown by Streamlit, normally:

```text
http://localhost:8501
```

The application works without an API key because template explanations are
enabled by default.

## 12. Test Commands

All tests are offline except for code paths that are explicitly designed for
future live network or API use.

```powershell
python tests/test_sample_data.py
python tests/test_scraper.py
python tests/test_rule_engine.py
python tests/test_nlp_extraction.py
python tests/test_orchestration.py
python tests/test_explanation.py
python tests/test_streamlit_app.py
```

The tests cover:

- Pydantic validation of the sample dataset.
- HTML-to-Scheme scraping.
- Eligible, not eligible, partially eligible, and manual-review outcomes.
- Age, income, lakh, monthly income, and categorical extraction.
- Profile merging across turns.
- Clarification question selection.
- Explanation templates and LLM fallback behavior.
- Real Streamlit interactions using `AppTest`.

## 13. Demonstration Scenario

Use this scenario during the presentation.

### First message

```text
I am 65 years old and live in Gujarat.
```

The extractor produces:

```text
age = 65
state = gujarat
```

Vay Vandana requires annual income information, so the engine returns
`PARTIALLY_ELIGIBLE`. The orchestration layer asks:

```text
What's your family's approximate annual income (in Rs.)?
```

### Second message

```text
My annual income is around 1 lakh rupees.
```

The extractor adds:

```text
annual_income = 100000
```

The rule engine checks:

- User age 65 is at least 60.
- Annual income Rs. 100,000 is below Rs. 150,000.
- User state Gujarat matches the scheme state.

The final result is:

```text
ELIGIBLE
```

## 14. Design Decisions for Presentation

### Why use a deterministic rule engine?

Eligibility decisions involve exact numbers, categories, and exclusions. A
language model may misread a threshold or produce inconsistent answers. A
deterministic engine gives the same result for the same profile and criteria,
and every result can be inspected condition by condition.

### Why use NLP if the rules are deterministic?

The rule engine needs structured fields, but users naturally write free text.
The NLP module is the conversion layer between human language and the
structured profile. It does not replace the rule engine.

### Why separate scraping and parsing?

Separating network access from parsing makes tests fast and offline. It also
allows a future API or browser-rendering fetcher to reuse the same parser.

### Why does `None` mean unrestricted?

The rule engine must distinguish between a scheme with no restriction and a
scheme that requires information from the user. That distinction prevents
unnecessary clarification questions.

### Why is manual review a separate result?

Some scheme conditions are too complex or too contextual for the current
structured fields. Marking them as manual review is safer than pretending the
system can certify eligibility.

## 15. Current Limitations

The current prototype has these limitations:

1. Only three sample schemes are included.
2. Retrieval currently returns every scheme instead of using semantic search.
3. ChromaDB or another vector database is not configured.
4. Conversations are not persisted in PostgreSQL.
5. Refreshing or closing the browser loses the current session.
6. Negation detection is incomplete.
7. Some free-text conditions require manual review.
8. Live JavaScript-rendered government pages may require browser rendering.
9. The vocabulary in `lookups.py` is hand-curated and incomplete.

These are known scope boundaries, not hidden behavior.

## 16. Future Scope

Possible future improvements are:

- Add PostgreSQL persistence for schemes, sessions, and chat logs.
- Add ChromaDB semantic retrieval.
- Add more verified schemes and administrative update tools.
- Improve negation and multi-value extraction.
- Add multilingual extraction for Indian languages.
- Add document upload and verification workflows.
- Add a FastAPI endpoint for non-Streamlit clients.
- Add authentication and user accounts.
- Add monitoring, audit logs, and scheme version history.

## 17. Presentation Conclusion

This project demonstrates a transparent and modular government scheme
eligibility chatbot. It combines validated Pydantic data models, HTML
scraping, rule-based NLP extraction, deterministic eligibility evaluation,
LangGraph conversation orchestration, grounded explanation generation, and a
Streamlit interface.

The central contribution is the separation between deciding and explaining.
The rule engine decides eligibility from structured criteria, while the
explanation layer communicates that decision to the user. This improves
reliability, transparency, repeatability, and testability compared with an
application that lets an LLM make eligibility decisions directly.

### Common viva question

**Why not allow the LLM to decide eligibility directly?**

An LLM can misunderstand numeric thresholds, exceptions, or missing values.
Therefore, this project uses structured criteria and a deterministic rule
engine for the decision. The LLM, when enabled, receives the completed result
and only converts it into natural language. This reduces hallucination and
makes the final decision explainable and testable.
#   G o v s c h e m e - B o t  
 