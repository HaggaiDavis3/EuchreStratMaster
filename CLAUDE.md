# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

EuchreStratMaster is a Euchre practice/coaching tool. You play the human seat (seat 0, "You & North" team) against three rule-based AI opponents, and after each hand a grader compares your bidding/card-play decisions against what the AI would have done, explaining mistakes and simulating counterfactual outcomes. There are two front ends over the same game logic: a terminal CLI and a FastAPI + vanilla-JS web app.

## Commands

Install dependencies:
```
pip install -r requirements.txt
```

Run the CLI game:
```
python main.py
python main.py --no-color   # disable colorama output
```

Run the web app (dev):
```
python -m uvicorn server:app --reload --port 8000
```
Then visit `http://localhost:8000/`. Production entrypoint is defined in `Procfile` (`uvicorn server:app --host 0.0.0.0 --port $PORT`), i.e. this is deployed as a Heroku-style web dyno.

There is no test suite, linter, or type-checker configured in this repo — verify changes by running the CLI and/or the web app manually.

## Architecture

### Shared core (`euchre/`)

- `cards.py` — `Suit`, `Rank`, `Card` (frozen dataclass with bower-aware `effective_suit`/`effective_rank`/`is_trump`), and `Deck`. This is the only place bower logic (left bower belongs to the trump suit) is defined at the card level.
- `rules.py` — pure functions over cards: `legal_plays`, `trick_winner`, `hand_points` (euchre/march/loner scoring), `partner_of`/`team_of` (seats 0,2 vs 1,3). No state, no I/O.
- `ai.py` — the single source of truth for "correct" Euchre strategy. `bid_decision()` scores a hand for a candidate trump suit and decides order-up/pass/call-suit/go-alone using score thresholds that shift with the current game score (e.g. lower bar when near 10 points). `card_to_play()` picks a lead/follow card and returns `(card, strategy_tag)`, where `strategy_tag` is a stable string key (e.g. `"LEAD_TRUMP_POWER"`, `"THROW_LOW_PARTNER_WINNING"`) consumed by the grader and by web hint text. This module is used for **both** the three AI opponents' actual moves **and** as the reference/"optimal" move for grading and hints — changing its heuristics changes opponent behavior and grading simultaneously.
- `grader.py` (`MoveGrader`) — replays a completed hand's recorded `BidDecision`/`CardPlay` entries, re-derives what `ai.py` would have done in the same situation, and produces `OPTIMAL`/`ACCEPTABLE`/`MISTAKE` verdicts plus human-readable explanations (`EXPLANATIONS` dict keyed by `strategy_tag`). For non-optimal card plays it can re-simulate the rest of the hand with the AI's suggested card substituted in (`_simulate_counterfactual`) to show the actual trick-count impact, and builds a prose `_narrative()` summary of the whole hand.
- `ui.py` — colorama-based terminal rendering and input prompts for the CLI only.
- `engine.py` — CLI orchestration (`GameEngine.run()`), a blocking loop that calls into `ui.py` for human input and `ai.py` for opponents, and builds the recording dataclasses (`BidDecision`, `CardPlay`, `HandRecord`) that `grader.py` consumes.
- `web_session.py` (`WebGameSession`) — a second, independent orchestration layer for the web app. Instead of a blocking loop, it's an explicit `Phase` state machine (`BIDDING_R1` → `BIDDING_R2` → `DISCARDING` → `PLAYING_TRICK` → `TRICK_COMPLETE` → `HAND_COMPLETE`/`GAME_OVER`) advanced one HTTP action at a time via `process_action()`, auto-running AI turns (`_run_ai_until_human`) until it's the human's turn again. It also generates in-the-moment hints (`_get_hint`, using `ai.py` + `EXPLANATIONS`/`_PLAY_HINT_CONTEXT`) and card-tracking/void-inference text (`_build_card_tracking`) that the CLI does not have.

**Important**: `engine.py` and `web_session.py` are parallel, independently-maintained implementations of the same game flow (dealing, bidding rounds, stick-the-dealer, dealer discard, trick play, scoring). They share `cards.py`/`rules.py`/`ai.py`/`grader.py` but duplicate orchestration logic (e.g. dealer-discard-for-AI is separately implemented in `GameEngine._dealer_discard` and `WebGameSession._handle_dealer_pickup`). A gameplay-rule change usually needs to be applied in both places if it should affect both the CLI and the web app.

### Web app (`server.py`, `static/`)

- `server.py` is a small FastAPI app with in-memory `sessions: dict[str, WebGameSession]` keyed by UUID (no persistence/DB — restarting the server loses all games). Three JSON endpoints (`/api/new-game`, `/api/action`, `/api/state/{session_id}`) plus static file serving.
- `static/game.js` is a vanilla-JS single-page client with no build step or framework: `sendAction()` posts an action object matching the action types handled in `WebGameSession.process_action` (`BID_R1`, `BID_R2`, `DISCARD`, `PLAY_CARD`, `NEXT_TRICK`, `REQUEST_GRADE`, `NEXT_HAND`, `NEW_GAME`), then a single `render(state)` dispatcher re-renders the whole UI from the JSON state blob returned by the server. Session ID is persisted in `localStorage` so a page refresh resumes the same game.
- Card IDs are `<rank_display><suit_letter>` strings (e.g. `"JS"` for jack of spades), serialized/deserialized between `Card` objects and JSON via `_serialize_card`/`CARD_LOOKUP` in `web_session.py`.

### Seats and teams

Seats are fixed: 0 = You (human), 1 = West, 2 = North (your partner), 3 = East. Teams are `seat % 2`, so team 0 is "You & North" and team 1 is "West & East" (see `PLAYER_NAMES`/`TEAM_NAMES` constants, duplicated in both `engine.py` and `web_session.py`).
