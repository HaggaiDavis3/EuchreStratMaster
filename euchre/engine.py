from __future__ import annotations
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from euchre.cards import Card, Deck, Suit
from euchre.rules import legal_plays, trick_winner, hand_points, partner_of, team_of
from euchre import ai

if TYPE_CHECKING:
    from euchre.ui import UI

HUMAN_SEAT = 0
PLAYER_NAMES = ["You", "West", "North", "East"]
# Teams: seats 0,2 vs seats 1,3
TEAM_NAMES = ["You & North", "West & East"]


# ---------------------------------------------------------------------------
# Data classes for recording decisions (used by grader)
# ---------------------------------------------------------------------------

@dataclass
class BidDecision:
    round: int
    seat: int
    hand_at_time: list[Card]
    upcard: Card | None
    excluded_suit: Suit | None
    score_at_time: list[int]
    human_choice: str       # "order"|"pass"|suit_value
    human_alone: bool
    dealer: int


@dataclass
class CardPlay:
    trick_num: int
    seat: int
    hand_at_time: list[Card]
    trick_so_far: list[tuple[int, Card]]
    tricks_won_at_time: list[int]  # [team0, team1]
    trump: Suit
    caller: int
    going_alone: bool
    human_card: Card
    played_cards_at_time: list[tuple[int, Card]] = field(default_factory=list)
    all_hands_at_time: dict[int, list[Card]] = field(default_factory=dict)
    trump_void_seats: frozenset[int] = field(default_factory=frozenset)


@dataclass
class HandRecord:
    dealer: int
    trump: Suit
    trump_caller: int
    going_alone: bool
    initial_hands: dict[int, list[Card]]
    bid_decisions: list[BidDecision]
    card_plays: list[CardPlay]
    hand_scores: list[int]   # [team0_tricks, team1_tricks]
    point_delta: list[int]   # [team0_pts, team1_pts] earned this hand


# ---------------------------------------------------------------------------
# Game engine
# ---------------------------------------------------------------------------

@dataclass
class GameState:
    scores: list[int] = field(default_factory=lambda: [0, 0])
    dealer: int = 0
    hand_history: list[HandRecord] = field(default_factory=list)


class GameEngine:
    def __init__(self, ui: UI) -> None:
        self.ui = ui
        self.state = GameState()

    def run(self) -> None:
        self.ui.welcome()
        while max(self.state.scores) < 10:
            record = self._play_hand()
            self.state.hand_history.append(record)
            self.state.dealer = (self.state.dealer + 1) % 4

        winner = 0 if self.state.scores[0] >= 10 else 1
        self.ui.game_over(TEAM_NAMES[winner], self.state.scores)

    # ------------------------------------------------------------------
    # Hand orchestration
    # ------------------------------------------------------------------

    def _play_hand(self) -> HandRecord:
        dealer = self.state.dealer
        self.ui.announce(f"\n{'='*60}")
        self.ui.announce(f"Score — {TEAM_NAMES[0]}: {self.state.scores[0]}  |  {TEAM_NAMES[1]}: {self.state.scores[1]}")
        self.ui.announce(f"Dealer: {PLAYER_NAMES[dealer]}")

        deck = Deck()
        hands, kitty = deck.deal()
        initial_hands = {i: list(hands[i]) for i in range(4)}
        upcard = kitty[0]

        self.ui.show_upcard(upcard)
        self.ui.show_hand(hands[HUMAN_SEAT], label="Your hand")

        bid_decisions: list[BidDecision] = []

        # --- Trump selection ---
        trump, caller, going_alone = self._trump_selection(
            hands, upcard, dealer, bid_decisions
        )
        if trump is None:
            # Misdeal — shouldn't happen with stick-the-dealer, but guard anyway
            self.ui.announce("All passed — redealing.")
            return self._play_hand()

        self.ui.announce(f"\nTrump: {trump.name}  |  Called by: {PLAYER_NAMES[caller]}"
                         + ("  [GOING ALONE]" if going_alone else ""))

        # Dealer picks up upcard if trump was ordered in round 1
        if going_alone or True:  # always refresh display after trump
            self.ui.show_hand(hands[HUMAN_SEAT], label="Your hand", trump=trump)

        # --- Play tricks ---
        card_plays: list[CardPlay] = []
        trick_counts = [0, 0]  # per team
        leader = (dealer + 1) % 4

        active_seats = [0, 1, 2, 3]
        if going_alone:
            # Partner of caller sits out
            active_seats = [s for s in active_seats if s != partner_of(caller)]

        for trick_num in range(5):
            trick_plays, plays_recorded = self._play_trick(
                hands, trick_num, leader, trump, caller, going_alone,
                active_seats, list(trick_counts), card_plays
            )
            winner_seat = trick_winner(trick_plays, trump)
            trick_counts[team_of(winner_seat)] += 1
            leader = winner_seat
            self.ui.announce(
                f"  → {PLAYER_NAMES[winner_seat]} wins trick {trick_num+1}"
                f"  (Team scores: {TEAM_NAMES[0]}: {trick_counts[0]}  {TEAM_NAMES[1]}: {trick_counts[1]})"
            )

        # --- Score ---
        caller_team = team_of(caller)
        pts = hand_points(trick_counts, caller_team, going_alone)
        for t in range(2):
            self.state.scores[t] += pts[t]

        self.ui.show_scores(self.state.scores, trick_counts, TEAM_NAMES)

        record = HandRecord(
            dealer=dealer,
            trump=trump,
            trump_caller=caller,
            going_alone=going_alone,
            initial_hands=initial_hands,
            bid_decisions=bid_decisions,
            card_plays=card_plays,
            hand_scores=trick_counts,
            point_delta=pts,
        )

        if self.ui.prompt_view_grade():
            from euchre.grader import MoveGrader
            report = MoveGrader().grade_hand(record)
            self.ui.show_grade_report(report)

        self.ui.wait_for_enter("\nPress Enter for next hand...")
        return record

    # ------------------------------------------------------------------
    # Trump selection
    # ------------------------------------------------------------------

    def _trump_selection(
        self,
        hands: list[list[Card]],
        upcard: Card,
        dealer: int,
        bid_decisions: list[BidDecision],
    ) -> tuple[Suit | None, int, bool]:
        """Returns (trump_suit, caller_seat, going_alone)."""
        order = [(dealer + 1 + i) % 4 for i in range(4)]

        # Round 1
        self.ui.announce(f"\nRound 1 bidding — upcard is {upcard}")
        for seat in order:
            is_dealer = (seat == dealer)
            if seat == HUMAN_SEAT:
                choice, alone = self.ui.prompt_bid_round1(
                    upcard=upcard,
                    is_dealer=is_dealer,
                    hand=hands[seat],
                )
            else:
                choice, alone = ai.bid_decision(
                    hand=hands[seat],
                    round=1,
                    dealer=dealer,
                    seat=seat,
                    upcard=upcard,
                    score=list(self.state.scores),
                )
                action_str = "orders up" if choice == "order" else "passes"
                self.ui.announce(f"  {PLAYER_NAMES[seat]} {action_str}"
                                 + (" and goes alone!" if alone else ""))

            bid_decisions.append(BidDecision(
                round=1, seat=seat,
                hand_at_time=list(hands[seat]),
                upcard=upcard, excluded_suit=None,
                score_at_time=list(self.state.scores),
                human_choice=choice, human_alone=alone,
                dealer=dealer,
            ))

            if choice == "order":
                # Dealer picks up the upcard, discards one
                if is_dealer:
                    hands[dealer].append(upcard)
                    discard = self._dealer_discard(hands[dealer], upcard.suit, dealer)
                    hands[dealer].remove(discard)
                return upcard.suit, seat, alone

        # Round 2
        self.ui.announce(f"\nRound 2 bidding — name a suit (not {upcard.suit.name})")
        for i, seat in enumerate(order):
            is_dealer = (seat == dealer)
            is_last = (i == 3)
            if seat == HUMAN_SEAT:
                choice, alone = self.ui.prompt_bid_round2(
                    excluded_suit=upcard.suit,
                    is_dealer=is_dealer,
                    hand=hands[seat],
                )
            else:
                choice, alone = ai.bid_decision(
                    hand=hands[seat],
                    round=2,
                    dealer=dealer,
                    seat=seat,
                    excluded_suit=upcard.suit,
                    score=list(self.state.scores),
                )
                if choice == "pass":
                    self.ui.announce(f"  {PLAYER_NAMES[seat]} passes")
                else:
                    suit = Suit(choice)
                    self.ui.announce(f"  {PLAYER_NAMES[seat]} calls {suit.name}"
                                     + (" and goes alone!" if alone else ""))

            bid_decisions.append(BidDecision(
                round=2, seat=seat,
                hand_at_time=list(hands[seat]),
                upcard=upcard, excluded_suit=upcard.suit,
                score_at_time=list(self.state.scores),
                human_choice=choice, human_alone=alone,
                dealer=dealer,
            ))

            if choice != "pass":
                return Suit(choice), seat, alone

        return None, -1, False

    def _dealer_discard(self, hand: list[Card], trump: Suit, dealer: int) -> Card:
        """AI dealers discard their weakest non-trump; human dealers are prompted."""
        if dealer == HUMAN_SEAT:
            return self.ui.prompt_discard(hand, trump)
        non_trumps = [c for c in hand if not c.is_trump(trump)]
        if non_trumps:
            return min(non_trumps, key=lambda c: c.effective_rank(trump))
        return min(hand, key=lambda c: c.effective_rank(trump))

    # ------------------------------------------------------------------
    # Trick play
    # ------------------------------------------------------------------

    def _play_trick(
        self,
        hands: list[list[Card]],
        trick_num: int,
        leader: int,
        trump: Suit,
        caller: int,
        going_alone: bool,
        active_seats: list[int],
        tricks_won: list[int],
        card_plays: list[CardPlay],
    ) -> tuple[list[tuple[int, Card]], list[CardPlay]]:
        self.ui.announce(f"\n--- Trick {trick_num + 1} ---")
        trick: list[tuple[int, Card]] = []
        plays_this_trick: list[CardPlay] = []

        order = []
        start = active_seats.index(leader) if leader in active_seats else 0
        for i in range(len(active_seats)):
            order.append(active_seats[(start + i) % len(active_seats)])

        for seat in order:
            lead_card = trick[0][1] if trick else None
            legal = legal_plays(hands[seat], lead_card, trump)

            if seat == HUMAN_SEAT:
                self.ui.show_trick(trick, trump, PLAYER_NAMES)
                self.ui.show_hand(hands[seat], label="Your hand", trump=trump, legal=legal)
                card = self.ui.prompt_card(hands[seat], legal)
            else:
                card, tag = ai.card_to_play(
                    hand=hands[seat],
                    trick=trick,
                    trump=trump,
                    seat=seat,
                    caller=caller,
                    going_alone=going_alone,
                )
                self.ui.announce(f"  {PLAYER_NAMES[seat]} plays {card}")

            if seat == HUMAN_SEAT:
                card_plays.append(CardPlay(
                    trick_num=trick_num,
                    seat=seat,
                    hand_at_time=list(hands[seat]),
                    trick_so_far=list(trick),
                    tricks_won_at_time=list(tricks_won),
                    trump=trump,
                    caller=caller,
                    going_alone=going_alone,
                    human_card=card,
                ))

            hands[seat].remove(card)
            trick.append((seat, card))

        return trick, plays_this_trick
