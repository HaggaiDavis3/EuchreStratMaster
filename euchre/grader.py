from __future__ import annotations
from dataclasses import dataclass, field
from euchre.cards import Card, Suit
from euchre.engine import BidDecision, CardPlay, HandRecord, HUMAN_SEAT, PLAYER_NAMES
from euchre.rules import partner_of, team_of, effective_suit, effective_rank
from euchre import ai

_ALL_TRUMP_RANKS: frozenset[int] = frozenset({100, 99, 14, 13, 12, 10, 9})
_TRUMP_RANK_NAMES: dict[int, str] = {100: "right bower", 99: "left bower", 14: "A", 13: "K", 12: "Q", 10: "10", 9: "9"}


EXPLANATIONS: dict[str, str] = {
    # Bidding
    "BID_MATCH": "Your choice matched the recommended play.",
    "BID_PASS_WEAK": "With a low hand score, passing was correct.",
    "BID_SHOULD_ORDER": "Your hand was strong enough to order up trump.",
    "BID_SHOULD_PASS": "Your hand was too weak to order up; passing was better.",
    "BID_ALONE_MISSED": "You had a strong enough hand to go alone but didn't declare it.",
    "BID_ALONE_WRONG": "Going alone here was risky; your hand wasn't strong enough.",
    "BID_SUIT_MATCH": "You called the best available suit.",
    "BID_WRONG_SUIT": "A different suit would have given you a stronger trump hand.",
    # Card play
    "LEAD_BOTH_BOWERS": "Lead the right bower when holding both bowers — control the trick immediately.",
    "LEAD_TRUMP_POWER": "With 3+ trump, lead high trump to pull opponents' trump.",
    "LEAD_TRUMP_CALLER": "You called trump with 2 trump — lead trump to establish control and flush opponents before they can void-suit you.",
    "LEAD_OFF_ACE_PARTNER_CALLED": "Partner called trump — lead an off-suit ace to win tricks before opponents can trump.",
    "LEAD_OFF_ACE_DEFENSE": "Opponents called trump — lead your off-suit ace to grab a free trick before they run their trump.",
    "LEAD_TRUMP_ALONE": "Going alone — lead highest trump to clear the way.",
    "LEAD_TRUMP_UNBEATABLE": "Your trump are now the highest remaining — lead trump to pull opponents' last trump before they can use it on your off-suit cards.",
    "LEAD_HIGHEST_OFFSUIT": "Lead your strongest off-suit card to establish tricks.",
    "LEAD_TRUMP_ONLY_OPTION": "No off-suit cards remaining; lead trump.",
    "WIN_TRICK": "Play the lowest card that wins the trick — efficient card use.",
    "WIN_TRICK_LAST": "Playing last — use the lowest winning card to conserve high cards.",
    "THROW_LOW_PARTNER_WINNING": "Partner is already winning — throw your lowest card to save good cards.",
    "THROW_LOW_TRUMP_PARTNER_WINNING": "Partner is winning and you only have trump — discard your lowest trump.",
    "THROW_LOW_CANT_WIN": "You can't win this trick — discard your lowest card.",
    "THROW_LOW_TRUMP_CANT_WIN": "You can't win even with trump — discard your lowest trump.",
    "THROW_LOW_SECOND_SEAT": "Playing 2nd in the trick — don't spend low trump when partner and 4th seat haven't acted; save your trump to overruff if needed.",
}


@dataclass
class BidGrade:
    decision: BidDecision
    verdict: str           # "OPTIMAL" | "ACCEPTABLE" | "MISTAKE"
    ai_action: str
    ai_alone: bool
    explanation: str


@dataclass
class PlayGrade:
    play: CardPlay
    verdict: str
    ai_card: Card
    ai_tag: str
    explanation: str
    counterfactual_note: str = ""


@dataclass
class GradeReport:
    bid_grades: list[BidGrade]
    play_grades: list[PlayGrade]
    summary: str
    narrative: str
    hand_scores: dict[int, float] = field(default_factory=dict)


class MoveGrader:
    def grade_hand(self, record: HandRecord) -> GradeReport:
        bid_grades = [
            self._grade_bid(d)
            for d in record.bid_decisions
            if d.seat == HUMAN_SEAT
        ]
        play_grades = [
            self._grade_play(p, record)
            for p in record.card_plays
            if p.seat == HUMAN_SEAT
        ]
        summary = self._summarize(bid_grades, play_grades, record)
        narrative = self._narrative(bid_grades, play_grades, record)
        hand_scores = {}
        if record.trump is not None:
            for seat, hand in record.initial_hands.items():
                hand_scores[seat] = ai._score_hand_for_trump(hand, record.trump)
        return GradeReport(bid_grades, play_grades, summary, narrative, hand_scores=hand_scores)

    # ------------------------------------------------------------------
    # Bid grading
    # ------------------------------------------------------------------

    def _grade_bid(self, d: BidDecision) -> BidGrade:
        ai_action, ai_alone = ai.bid_decision(
            hand=d.hand_at_time,
            round=d.round,
            dealer=d.dealer,
            seat=d.seat,
            upcard=d.upcard,
            excluded_suit=d.excluded_suit,
            score=d.score_at_time,
        )

        human = d.human_choice
        h_alone = d.human_alone

        # Determine verdict
        if d.round == 1:
            verdict, tag = self._compare_bid_r1(human, h_alone, ai_action, ai_alone)
        else:
            verdict, tag = self._compare_bid_r2(human, h_alone, ai_action, ai_alone)

        return BidGrade(d, verdict, ai_action, ai_alone, EXPLANATIONS.get(tag, tag))

    def _compare_bid_r1(
        self, human: str, h_alone: bool,
        ai_action: str, ai_alone: bool
    ) -> tuple[str, str]:
        if human == ai_action:
            if human == "pass":
                return "OPTIMAL", "BID_PASS_WEAK"
            if h_alone == ai_alone:
                return "OPTIMAL", "BID_MATCH"
            if ai_alone and not h_alone:
                return "ACCEPTABLE", "BID_ALONE_MISSED"
            return "ACCEPTABLE", "BID_MATCH"
        if human == "order" and ai_action == "pass":
            return "MISTAKE", "BID_SHOULD_PASS"
        if human == "pass" and ai_action == "order":
            return "MISTAKE", "BID_SHOULD_ORDER"
        return "ACCEPTABLE", "BID_MATCH"

    def _compare_bid_r2(
        self, human: str, h_alone: bool,
        ai_action: str, ai_alone: bool
    ) -> tuple[str, str]:
        if human == "pass" and ai_action == "pass":
            return "OPTIMAL", "BID_PASS_WEAK"
        if human == ai_action:
            if h_alone == ai_alone:
                return "OPTIMAL", "BID_SUIT_MATCH"
            if ai_alone and not h_alone:
                return "ACCEPTABLE", "BID_ALONE_MISSED"
            return "OPTIMAL", "BID_SUIT_MATCH"
        if human == "pass" and ai_action != "pass":
            return "MISTAKE", "BID_SHOULD_ORDER"
        if human != "pass" and ai_action == "pass":
            return "MISTAKE", "BID_SHOULD_PASS"
        # Both called but different suits
        return "MISTAKE", "BID_WRONG_SUIT"

    # ------------------------------------------------------------------
    # Card play grading
    # ------------------------------------------------------------------

    def _grade_play(self, p: CardPlay, record: HandRecord) -> PlayGrade:
        ai_card, ai_tag = ai.card_to_play(
            hand=p.hand_at_time,
            trick=p.trick_so_far,
            trump=p.trump,
            seat=p.seat,
            caller=p.caller,
            going_alone=p.going_alone,
            played_cards=p.played_cards_at_time,
            trump_void_seats=p.trump_void_seats,
        )

        verdict = self._compare_play(p.human_card, ai_card, p.trump)

        # Throw-off equivalence: when neither player can win, any discard choice is acceptable
        _THROW_TAGS = {
            "THROW_LOW_CANT_WIN", "THROW_LOW_TRUMP_CANT_WIN",
            "THROW_LOW_PARTNER_WINNING", "THROW_LOW_TRUMP_PARTNER_WINNING",
        }
        if verdict == "MISTAKE" and ai_tag in _THROW_TAGS and p.trick_so_far:
            human_can_win = ai._lowest_winner([p.human_card], p.trick_so_far, p.trump) is not None
            if not human_can_win or ai_tag in {"THROW_LOW_PARTNER_WINNING", "THROW_LOW_TRUMP_PARTNER_WINNING"}:
                verdict = "ACCEPTABLE"

        explanation = EXPLANATIONS.get(ai_tag, ai_tag)
        if verdict != "OPTIMAL":
            explanation = f"AI recommended {ai_card} — {explanation}"

        counterfactual_note = ""
        if verdict in ("MISTAKE", "ACCEPTABLE") and p.all_hands_at_time:
            sim = self._simulate_counterfactual(p, ai_card, record)
            if sim is not None:
                human_team = team_of(HUMAN_SEAT)
                actual = record.hand_scores[human_team]
                simulated = sim[human_team]
                tw = lambda n: f"{n} trick{'s' if n != 1 else ''}"

                if verdict == "MISTAKE":
                    if simulated > actual:
                        diff = simulated - actual
                        counterfactual_note = (
                            f"Simulation: playing {ai_card} here leads to {tw(simulated)} for your team"
                            f" vs the actual {actual} — a gain of {tw(diff)}."
                        )
                    elif simulated == actual:
                        verdict = "ACCEPTABLE"
                        counterfactual_note = (
                            f"Simulation: playing {ai_card} still produces {tw(actual)} for your team — "
                            f"the same result. Suboptimal in principle, but this specific hand made it a wash."
                        )
                    else:
                        verdict = "ACCEPTABLE"
                        counterfactual_note = (
                            f"Simulation: {ai_card} only produces {tw(simulated)} vs your actual {actual} — "
                            f"your play happened to be better here. The general principle still favors {ai_card}."
                        )
                else:  # ACCEPTABLE
                    ctx = self._build_play_context(p)
                    if simulated > actual:
                        diff = simulated - actual
                        counterfactual_note = (
                            f"Simulation: {ai_card} would have yielded {tw(simulated)} vs your {actual}"
                            f" — a {tw(diff)} advantage. Your play was reasonable but this hand had a cleaner line."
                            + (f"\n{ctx}" if ctx else "")
                        )
                    elif simulated == actual:
                        counterfactual_note = (
                            f"Simulation confirms: {ai_card} produces the same {tw(actual)} for your team"
                            f" — the two choices were equivalent in this hand."
                            + (f"\n{ctx}" if ctx else "")
                        )
                    else:
                        diff = actual - simulated
                        counterfactual_note = (
                            f"Simulation: {ai_card} only produces {tw(simulated)} vs your {actual}"
                            f" — your play was actually the better choice here by {tw(diff)}."
                            + (f"\n{ctx}" if ctx else "")
                        )

        return PlayGrade(p, verdict, ai_card, ai_tag, explanation, counterfactual_note)

    def _simulate_counterfactual(
        self, p: CardPlay, ai_card: Card, record: HandRecord
    ) -> list[int] | None:
        """Replay remaining tricks with ai_card substituted for human's actual play.
        Returns final [team0_tricks, team1_tricks] or None on failure."""
        from euchre.rules import trick_winner, partner_of

        if ai_card not in p.all_hands_at_time.get(HUMAN_SEAT, []):
            return None

        trump, caller, going_alone = p.trump, p.caller, p.going_alone
        active_seats = [s for s in [0, 1, 2, 3]
                        if not going_alone or s != partner_of(caller)]
        n = len(active_seats)

        sim_hands = {seat: list(cards) for seat, cards in p.all_hands_at_time.items()}
        sim_hands[HUMAN_SEAT].remove(ai_card)

        trick_leader = p.trick_so_far[0][0] if p.trick_so_far else HUMAN_SEAT
        leader_idx = active_seats.index(trick_leader)
        play_order = [active_seats[(leader_idx + i) % n] for i in range(n)]
        human_idx = play_order.index(HUMAN_SEAT)

        current_trick = list(p.trick_so_far) + [(HUMAN_SEAT, ai_card)]
        sim_played = list(p.played_cards_at_time)
        sim_trump_voids = set(p.trump_void_seats)

        def _update_trump_voids(trick: list) -> None:
            _, led_card = trick[0]
            if led_card.is_trump(trump):
                for s, c in trick[1:]:
                    if not c.is_trump(trump):
                        sim_trump_voids.add(s)

        # Complete current trick (players after human)
        for seat in play_order[human_idx + 1:]:
            card, _ = ai.card_to_play(
                hand=sim_hands[seat], trick=current_trick, trump=trump,
                seat=seat, caller=caller, going_alone=going_alone,
                played_cards=sim_played,
                trump_void_seats=frozenset(sim_trump_voids),
            )
            sim_hands[seat].remove(card)
            current_trick.append((seat, card))

        sim_counts = list(p.tricks_won_at_time)
        winner = trick_winner(current_trick, trump)
        sim_counts[team_of(winner)] += 1
        _update_trump_voids(current_trick)
        sim_played.extend(current_trick)
        next_leader = winner

        # Play all remaining tricks
        for _ in range(5 - (p.trick_num + 1)):
            leader_idx = active_seats.index(next_leader)
            trick = []
            for seat in [active_seats[(leader_idx + i) % n] for i in range(n)]:
                card, _ = ai.card_to_play(
                    hand=sim_hands[seat], trick=trick, trump=trump,
                    seat=seat, caller=caller, going_alone=going_alone,
                    played_cards=sim_played,
                    trump_void_seats=frozenset(sim_trump_voids),
                )
                sim_hands[seat].remove(card)
                trick.append((seat, card))
            winner = trick_winner(trick, trump)
            sim_counts[team_of(winner)] += 1
            _update_trump_voids(trick)
            sim_played.extend(trick)
            next_leader = winner

        return sim_counts

    def _build_play_context(self, p: CardPlay) -> str:
        """Describe game state at time of play: trump accounting, per-player history, confirmed voids."""
        trump = p.trump
        played = p.played_cards_at_time
        if not played:
            return ""

        n_active = 3 if p.going_alone else 4

        # Reconstruct trick boundaries (played list is in play order, n_active cards per trick)
        tricks: list[list[tuple[int, Card]]] = []
        for i in range(0, len(played), n_active):
            chunk = played[i : i + n_active]
            if chunk:
                tricks.append(chunk)

        # Per-seat card history
        by_seat: dict[int, list[Card]] = {0: [], 1: [], 2: [], 3: []}
        for seat, card in played:
            by_seat[seat].append(card)

        # Confirmed suit voids from trick structure
        voids: dict[int, set[Suit]] = {1: set(), 2: set(), 3: set()}
        for trick in tricks:
            if len(trick) < 2:
                continue
            _, led_card = trick[0]
            led = effective_suit(led_card, trump)
            for seat, card in trick[1:]:
                if seat in voids and effective_suit(card, trump) != led:
                    voids[seat].add(led)

        # Trump accounting
        played_trump = [(seat, c) for seat, c in played if c.is_trump(trump)]
        my_trump = [c for c in p.hand_at_time if c.is_trump(trump)]
        played_trump_ranks = {effective_rank(c, trump) for _, c in played_trump}
        my_trump_ranks = {effective_rank(c, trump) for c in my_trump}
        unaccounted = _ALL_TRUMP_RANKS - played_trump_ranks - my_trump_ranks

        parts: list[str] = []

        # Trump summary
        from euchre.cards import SUIT_UNICODE
        sym = SUIT_UNICODE[trump]

        if played_trump:
            trump_descs = []
            for seat, c in sorted(played_trump, key=lambda x: effective_rank(x[1], trump), reverse=True):
                rname = _TRUMP_RANK_NAMES.get(effective_rank(c, trump), str(effective_rank(c, trump)))
                trump_descs.append(f"{rname}{sym} by {PLAYER_NAMES[seat]}")
            parts.append(f"Trump played ({len(played_trump)}/7): {', '.join(trump_descs)}.")
            if unaccounted:
                ua_names = [_TRUMP_RANK_NAMES.get(r, str(r)) + sym for r in sorted(unaccounted, reverse=True)]
                parts.append(f"Unaccounted trump (in opponents' hands or kitty): {', '.join(ua_names)}.")
            else:
                parts.append("All remaining trump were in your hand.")
        else:
            parts.append("No trump had been played yet.")

        # Per-opponent summary
        for seat in [1, 2, 3]:
            cards = by_seat[seat]
            if not cards:
                continue
            card_strs = [str(c) for c in cards]
            void_note = ""
            if voids.get(seat):
                void_syms = [SUIT_UNICODE[s] for s in sorted(voids[seat], key=lambda s: s.value)]
                void_note = f"; confirmed void in {' '.join(void_syms)}"
            parts.append(f"{PLAYER_NAMES[seat]}: {', '.join(card_strs)}{void_note}.")

        return " ".join(parts)

    def _compare_play(self, human: Card, ai_card: Card, trump: Suit) -> str:
        if human == ai_card:
            return "OPTIMAL"
        # Same effective rank and suit = equivalent card
        if (human.effective_rank(trump) == ai_card.effective_rank(trump)
                and human.effective_suit(trump) == ai_card.effective_suit(trump)):
            return "OPTIMAL"
        # Same suit family and close in rank = acceptable
        if human.effective_suit(trump) == ai_card.effective_suit(trump):
            rank_diff = abs(human.effective_rank(trump) - ai_card.effective_rank(trump))
            if rank_diff <= 2:
                return "ACCEPTABLE"
        return "MISTAKE"

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def _summarize(
        self,
        bid_grades: list[BidGrade],
        play_grades: list[PlayGrade],
        record: HandRecord,
    ) -> str:
        bid_opt = sum(1 for g in bid_grades if g.verdict == "OPTIMAL")
        bid_tot = len(bid_grades)
        play_opt = sum(1 for g in play_grades if g.verdict == "OPTIMAL")
        play_acc = sum(1 for g in play_grades if g.verdict == "ACCEPTABLE")
        play_mis = sum(1 for g in play_grades if g.verdict == "MISTAKE")
        play_tot = len(play_grades)

        caller_name = "You" if record.trump_caller == 0 else f"Player {record.trump_caller}"
        outcome = ""
        your_team_tricks = record.hand_scores[0]  # team 0 is human's team
        if record.point_delta[0] > 0:
            outcome = f"Your team scored {record.point_delta[0]} point(s)."
        elif record.point_delta[1] > 0:
            outcome = f"Opponents scored {record.point_delta[1]} point(s)."

        lines = [
            f"Trump: {record.trump.name} (called by {caller_name}). {outcome}",
            f"Bidding: {bid_opt}/{bid_tot} optimal.",
            f"Card play: {play_opt}/{play_tot} optimal"
            + (f", {play_acc} acceptable" if play_acc else "")
            + (f", {play_mis} mistake(s)" if play_mis else "") + ".",
        ]
        return "  ".join(lines)

    def _narrative(
        self,
        bid_grades: list[BidGrade],
        play_grades: list[PlayGrade],
        record: HandRecord,
    ) -> str:
        caller_team = team_of(record.trump_caller)
        human_team = team_of(HUMAN_SEAT)
        caller_tricks = record.hand_scores[caller_team]
        defender_tricks = record.hand_scores[1 - caller_team]
        human_called = (record.trump_caller == HUMAN_SEAT)
        partner_called = (record.trump_caller == partner_of(HUMAN_SEAT))
        your_team_called = (caller_team == human_team)
        opponent_called = not your_team_called
        euchred = caller_tricks < 3
        march = caller_tricks == 5
        going_alone = record.going_alone
        caller_name = PLAYER_NAMES[record.trump_caller]
        trump_name = record.trump.name
        your_pts = record.point_delta[human_team]
        opp_pts = record.point_delta[1 - human_team]
        human_sat_out = going_alone and partner_called

        bid_mistakes = [g for g in bid_grades if g.verdict == "MISTAKE"]
        play_mistakes = [g for g in play_grades if g.verdict == "MISTAKE"]
        play_clean = not play_mistakes  # True even if no plays recorded (sat out)
        all_clean = not bid_mistakes and play_clean

        tw = lambda n: f"{n} trick{'s' if n != 1 else ''}"
        parts: list[str] = []

        # ------------------------------------------------------------------
        # Part 1: What happened — specific, going-alone aware
        # ------------------------------------------------------------------
        if going_alone:
            if human_called:
                if march:
                    parts.append(f"You called {trump_name} and went alone, sweeping all 5 tricks for 4 points — a dominant solo run.")
                elif euchred:
                    parts.append(f"You called {trump_name} and went alone, but the defense held you to {tw(caller_tricks)} — an euchre worth 2 points to the opponents.")
                else:
                    parts.append(f"You called {trump_name} and went alone, taking {tw(caller_tricks)} for {your_pts} point.")
            elif partner_called:
                outcome_str = (
                    "swept all 5 tricks for 4 points" if march
                    else f"was euchred — held to {tw(caller_tricks)}, handing opponents 2 points" if euchred
                    else f"took {tw(caller_tricks)} for {your_pts} point"
                )
                parts.append(f"Your partner (North) called {trump_name} and went alone — you sat this hand out — and {outcome_str}.")
            else:
                outcome_str = (
                    f"swept all 5 tricks for 4 points" if march
                    else f"was euchred — your team held them to {tw(caller_tricks)} for 2 points to your side" if euchred
                    else f"took {tw(caller_tricks)} of 5, scoring {opp_pts} point"
                )
                parts.append(f"{caller_name} called {trump_name} and went alone (North sat out), and {outcome_str}.")
        else:
            if euchred and your_team_called:
                sub = "you were" if human_called else "your partner was"
                parts.append(f"{'You' if human_called else 'Your partner'} called {trump_name} but {sub} euchred — the defense held the callers to {tw(caller_tricks)}, handing opponents 2 points.")
            elif euchred:
                parts.append(f"The opponents called {trump_name} but your team euchred them — you held the callers to {tw(caller_tricks)}, earning 2 points.")
            elif march and your_team_called:
                sub = "you" if human_called else "your partner"
                parts.append(f"{'You' if human_called else 'Your partner'} called {trump_name} and marched all 5 tricks for 2 points — {sub} held dominant trump from start to finish.")
            elif march:
                parts.append(f"The opponents called {trump_name} and marched all 5 tricks for 2 points — they held dominant trump power and there was limited room to defend.")
            elif your_team_called:
                sub = "you" if human_called else "your partner"
                parts.append(f"{'You' if human_called else 'Your partner'} called {trump_name} and made it with {tw(caller_tricks)} for {your_pts} point.")
            else:
                parts.append(f"The opponents called {trump_name} and made it with {tw(caller_tricks)}, scoring {opp_pts} point.")

        # ------------------------------------------------------------------
        # Part 2: Performance assessment — contextual, situation-specific
        # ------------------------------------------------------------------
        if human_sat_out:
            if bid_mistakes:
                parts.append("Your bidding during the hand had a misstep — see the play-by-play grades above.")
            else:
                parts.append("Nothing to do but watch — your bidding during the hand was sound.")
        elif going_alone and opponent_called:
            n_err = len(play_mistakes)
            if march and all_clean:
                parts.append("You played your cards correctly throughout — when an opponent holds that kind of trump concentration, even perfect defense often can't prevent a march.")
            elif march and play_mistakes:
                parts.append(f"There {'was' if n_err == 1 else 'were'} {n_err} play decision{'s' if n_err > 1 else ''} that didn't match the optimal line — against a lone hand every margin matters since your partner couldn't cover.")
            elif euchred and all_clean:
                parts.append("That's a great defensive result — euchring a lone hand requires staying disciplined with your trump and not over-committing.")
            elif euchred and play_mistakes:
                parts.append(f"The euchre is a great result even with {n_err} suboptimal play{'s' if n_err > 1 else ''} — review the grades to sharpen your lone-hand defense further.")
            elif all_clean:
                parts.append(f"You played your cards correctly — limiting a lone hand to {tw(defender_tricks)} won by your side is genuine defensive success.")
            else:
                parts.append(f"There {'was' if n_err == 1 else 'were'} {n_err} play decision{'s' if n_err > 1 else ''} that could have been sharper — see the grades above for specifics.")
        elif all_clean:
            if euchred and your_team_called:
                parts.append("Your card play was sound throughout — the euchre points back to the bid; it's worth asking whether the hand was strong enough to order up.")
            elif march and your_team_called:
                parts.append("Excellent execution from bid to last card.")
            elif march and opponent_called:
                parts.append("Even with solid defense, a marching hand from the other side is hard to stop — sometimes they simply hold the cards.")
            elif euchred and opponent_called:
                parts.append("Clean, well-timed defense — you read the position well and capitalized on their overreach.")
            else:
                parts.append("Your decisions throughout this hand were well-calibrated.")

        # ------------------------------------------------------------------
        # Part 3: Key lesson — only when mistakes exist
        # ------------------------------------------------------------------
        _PLAY_LESSONS = {
            "THROW_LOW_PARTNER_WINNING":
                "When your partner is winning the trick, throw your lowest card — your high cards are needed for tricks where you actually have to fight.",
            "THROW_LOW_TRUMP_PARTNER_WINNING":
                "Even when you only have trump remaining, discard your lowest when partner already has the trick covered.",
            "LEAD_BOTH_BOWERS":
                "Holding both bowers means you lead trump immediately — right bower first, every time.",
            "LEAD_TRUMP_POWER":
                "With 3+ trump, lead high to strip opponents of their trump before they can use it.",
            "LEAD_TRUMP_CALLER":
                "When you called trump with 2 trump in hand, lead trump early — establish control before opponents can void-suit you.",
            "WIN_TRICK":
                "Win tricks with your weakest winning card — don't spend a bower when a low trump does the job.",
            "WIN_TRICK_LAST":
                "Playing last gives you full information — use the lowest card that still wins.",
            "THROW_LOW_CANT_WIN":
                "When you can't win, throw your lowest non-trump to preserve strong cards for later.",
            "LEAD_OFF_ACE_PARTNER_CALLED":
                "When your partner called trump, lead off-suit aces first so they can save trump for the tricks that matter.",
            "LEAD_OFF_ACE_DEFENSE":
                "When defending opponents' trump, lead off-suit aces first — win free tricks before they run their trump.",
            "LEAD_TRUMP_UNBEATABLE":
                "When every higher trump is gone, lead your remaining trump to flush out opponents' lower ones before they can use them.",
            "THROW_LOW_SECOND_SEAT":
                "Playing 2nd, save your trump — your partner and the 4th player may handle it without you spending a trump.",
        }

        if not human_sat_out:
            if bid_mistakes:
                g = bid_mistakes[0]
                too_passive = (
                    (g.decision.human_choice == "pass" and g.ai_action == "order")
                    or (g.ai_action not in ("order", "pass") and g.decision.human_choice == "pass")
                )
                lesson = (
                    "Don't be too conservative — when your hand has 3+ trump equivalent, ordering up is right even if it feels risky."
                    if too_passive else
                    "Calling trump on a weak hand is one of the costliest mistakes in Euchre — the bar is 3 solid trump, not wishful thinking."
                )
                parts.append(f"Key lesson: {lesson}")
            elif play_mistakes:
                tag = play_mistakes[0].ai_tag
                lesson = _PLAY_LESSONS.get(
                    tag,
                    "Read your partner's plays as carefully as your own hand — react to what they show you.",
                )
                n = len(play_mistakes)
                prefix = f"Key lesson ({n} play mistakes): " if n > 1 else "Key lesson: "
                parts.append(f"{prefix}{lesson}")

        return " ".join(parts)
