# testFAILS3

testFAILS3 is an autonomous, provenance-preserving successor to the testFAILS and testFAILS-2 research frameworks. It turns repeatable parts of the earlier manual methodology into a scheduled evaluation pipeline while preserving explicit boundaries around human preference, safety certification, and unsupported capabilities.

Research basis: [testFAILS (Electronics 2023, 12, 3095)](https://doi.org/10.3390/electronics12143095) and [testFAILS-2 (Electronics 2024, 13, 4991)](https://doi.org/10.3390/electronics13244991). The first paper introduced seven evaluation dimensions; the second expanded the framework to fourteen and identified automation and a continuously updated web platform as future work.

## What is real

- Provider responses come from configured APIs. If no credential exists, no model result is created.
- Arena context comes from Arena's official public `lmarena-ai/leaderboard-dataset` on Hugging Face.
- Every run records its model identifier, timestamps, deterministic suite hash, prompt and fixture hashes, typed assertion outcomes, response hashes, latency, token counts when returned, categorized errors, score, and coverage.
- Fourteen dimensions now contain five version-pinned probes each (70 total). Arena ranks remain a separate measurement and are never blended into the testFAILS3 score.
- The suite manifest freezes contextual dates and seeds. Runtime timestamps remain run metadata and never enter prompts or the suite digest.
- Exact, Pydantic schema, synonym/lemma, and provider-embedding cosine assertions are selected according to construct. The emotional-response probes use a declared cosine threshold of 0.85.

## Autonomous operation

The scheduled GitHub Action runs daily and can also be started manually. It:

1. runs the implementation tests;
2. synchronizes current Arena text, agent, search, and web-development leaderboards;
3. evaluates every provider whose repository secret is configured;
4. commits changed evidence to `data/`;
5. lets the production deployment update from `main`.

Required repository secrets are optional individually: `OPENAI_API_KEY`, `GEMINI_API_KEY`, or `TESTFAILS_COMPAT_API_KEY`. A local Hugging Face/TGI OpenAI-compatible server can be configured with `TESTFAILS_LOCAL_HF_BASE_URL` and `TESTFAILS_LOCAL_HF_MODEL`. Model, embedding, and endpoint settings use the variables documented in `.env.example`.

## Local use

```powershell
python -m pip install -r requirements.txt pytest
python -m testfails.cli sync-arena
python -m testfails.cli --env-file .env evaluate
python -m pytest -q
python app.py
```

Open `http://127.0.0.1:8063`.

## API

- `GET /api/status` - suite, Arena synchronization, and latest run
- `GET /api/arena` - exact synchronized external record
- `GET /api/runs/latest` - latest completed provider evaluation or an honest 404

## Autonomous 3D robot laboratory

Open `/robot-arena` to run the browser-based six-robot sandbox. A seeded evolutionary search performs 864 deterministic fitness evaluations to design the challenger, then all six controllers use grid-based A* navigation, line-of-sight checks, utility decisions, and simulated energy-pulse collision. The page reports live replans, travel, shots, hits, health, eliminations, and winner, and can export the complete run record as JSON. Re-entering the same seed reproduces the robot design, arena, and initial conditions.

The sandbox does not call an LLM or control hardware. Its "AI" label refers specifically to the implemented evolutionary optimizer and autonomous controllers. Three.js 0.180.0 is vendored under `static/vendor/three/` so rendering has no CDN dependency; its MIT license is included beside the library.

## Measurement boundaries

The conversational cases are reproducible proxies, not a Turing test. The security cases are bounded probes, not certification. The robot cases are simulations and cannot operate hardware. The first multimodal probe remains a synthetic 8x4 sanity check; four additional probes use committed research figures for chart reading and OCR. A score is meaningful only with its suite version and coverage. Provider errors stay categorized errors; they are not converted to zeros or silently retried with a different model.

The committed evidence predates suite version 2026.10.2 and remains preserved as historical evidence. It must not be compared directly with a new 70-probe run. A provider with depleted billing is recorded as `billing_depleted` with zero coverage and no score; authentication, rate-limit, schema, and timeout failures are likewise kept distinct.
