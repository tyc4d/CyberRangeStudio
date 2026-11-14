# Recorded LLM responses

Raw `gpt-4.1-mini` responses captured on 2026-11-15 from real runs of the fixtures in
`fixtures/sample-scenarios/` (before the overnight prompt changes). Unit tests replay them
through `app.cti.analysis` instead of calling the API. They are model *inputs to the program
rules*, kept unedited, including the model's mistakes — that is what the rules are tested against.
