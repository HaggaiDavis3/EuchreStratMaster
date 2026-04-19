from __future__ import annotations
import time
import uuid
from enum import Enum

from euchre.cards import Card, Deck, Rank, Suit, RANK_DISPLAY
from euchre.rules import legal_plays, trick_winner, hand_points, partner_of, team_of, is_right_bower, is_left_bower
from euchre.engine import BidDecision, CardPlay, HandRecord
from euchre import ai

HUMAN_SEAT = 0
PLAYER_NAMES = ["You", "West", "North", "East"]
TEAM_NAMES = ["You & North", "West & East"]

# ---------------------------------------------------------------------------
# Card serialization helpers
# ---------------------------------------------------------------------------

RED_SUITS = {Suit.HEARTS, Suit.DIAMONDS}
SUIT_SYMBOLS = {Suit.SPADES: "♠", Suit.CLUBS: "♣", Suit.HEARTS: "♥", Suit.DIAMONDS: "♦"}


def _serialize_card(card: Card) -> dict:
    rank_str = RANK_DISPLAY[card.rank]
    suit_str = card.suit.value
    return {
        "rank": rank_str,
        "suit": suit_str,
        "display": rank_str + SUIT_SYMBOLS[card.suit],
        "is_red": card.suit in RED_SUITS,
        "id": rank_str + suit_str,
    }


# Build lookup table for deserializing card IDs from the frontend
CARD_LOOKUP: dict[str, Card] = {
    RANK_DISPLAY[rank] + suit.value: Card(rank, suit)
    for suit in Suit
    for rank in Rank
}


def _deserialize_card(card_id: str) -> Card | None:
    return CARD_LOOKUP.get(card_id)


# ---------------------------------------------------------------------------
# Phase enum
# ---------------------------------------------------------------------------

_PLAY_HINT_CONTEXT: dict[str, tuple[str, str]] = {
    "LEAD_BOTH_BOWERS": (
        "You hold both the right and left bower — the two highest cards in all of Euchre.",
        "No other card can beat either bower, so leading the right bower immediately seizes control before opponents can act.",
    ),
    "LEAD_TRUMP_POWER": (
        "With 3+ trump in hand, you have enough to pull all the opponents' trump before they can use it on your tricks.",
        "Leading high trump strips opponents of their trump so your weaker cards won't get trumped in later tricks.",
    ),
    "LEAD_TRUMP_CALLER": (
        "You called trump with 2 trump in hand — leading trump immediately is the right move.",
        "Flushing opponents' trump early prevents them from voiding a side suit and trumping your aces later.",
    ),
    "LEAD_OFF_ACE_PARTNER_CALLED": (
        "Your partner called trump, meaning they're likely holding the strong trump themselves.",
        "Leading your off-suit ace grabs a free trick and lets your partner save their trump for the tricks that matter.",
    ),
    "LEAD_OFF_ACE_DEFENSE": (
        "The opponents called trump, so they hold the power — your best move is to win side tricks before they run trump.",
        "Lead your off-suit ace now; once opponents start pulling trump, any unplayed aces become easy targets.",
    ),
    "LEAD_TRUMP_ALONE": (
        "Going alone means your partner sits out, so you need to control every trick yourself.",
        "Leading your highest trump immediately clears opponents' trump so your remaining cards can win uncontested.",
    ),
    "LEAD_TRUMP_UNBEATABLE": (
        "Every trump ranked above yours has already been played this hand, making your trump the highest still in circulation.",
        "Lead trump now to force out opponents' lower trump — once their trump are gone, your off-suit cards win safely.",
    ),
    "LEAD_HIGHEST_OFFSUIT": (
        "No compelling reason to lead trump here, so lead your strongest off-suit card to probe the field.",
        "This may win outright, or reveals who can follow suit and who is holding trump in reserve.",
    ),
    "LEAD_TRUMP_ONLY_OPTION": (
        "You have no off-suit cards remaining, so every legal lead is trump.",
        "Lead your highest trump to maximize your chance of taking the trick.",
    ),
    "WIN_TRICK": (
        "An opponent is currently winning — use the cheapest card in your hand that still beats them.",
        "Don't spend a bower when a lower trump wins the same trick; save the big cards for tougher moments ahead.",
    ),
    "WIN_TRICK_LAST": (
        "Playing last gives you full information — you can see exactly what beats the current best play.",
        "Use the minimum card that still wins; the last-to-play position is an advantage worth exploiting cheaply.",
    ),
    "THROW_LOW_PARTNER_WINNING": (
        "Your partner is currently winning this trick — spending a strong card here only wastes it.",
        "Discard your weakest card to save everything for tricks where you actually need to fight.",
    ),
    "THROW_LOW_TRUMP_PARTNER_WINNING": (
        "You only have trump left, but your partner has the trick already covered.",
        "Even so, discard your lowest trump rather than a higher one — you may need higher trump in a later trick.",
    ),
    "THROW_LOW_CANT_WIN": (
        "No card in your legal plays can beat the current best — either trump is out or the led suit outranks you.",
        "Cut losses by discarding your weakest card and reserving any strong cards for tricks you can actually win.",
    ),
    "THROW_LOW_TRUMP_CANT_WIN": (
        "Even trump can't win here — a higher trump has already been played or the current card outranks yours.",
        "Discard the lowest trump to minimize damage and save higher trump for situations where it can take the lead.",
    ),
    "THROW_LOW_SECOND_SEAT": (
        "You're playing 2nd in this trick — partner and the 4th seat player (likely an opponent) haven't acted yet.",
        "Spending low trump now risks losing it for nothing; save it to overruff if the opponent in 4th seat tries to take the trick.",
    ),
}


class Phase(str, Enum):
    BIDDING_R1    = "BIDDING_R1"
    BIDDING_R2    = "BIDDING_R2"
    DISCARDING    = "DISCARDING"
    PLAYING_TRICK = "PLAYING_TRICK"
    TRICK_COMPLETE = "TRICK_COMPLETE"
    HAND_COMPLETE = "HAND_COMPLETE"
    GAME_OVER     = "GAME_OVER"


# ---------------------------------------------------------------------------
# WebGameSession
# ---------------------------------------------------------------------------

class WebGameSession:
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.last_active = time.time()

        # Persistent
        self.scores: list[int] = [0, 0]
        self.dealer: int = 0
        self.hand_number: int = 1
        self.hand_history: list[HandRecord] = []

        # Per-hand (set by _start_new_hand)
        self.phase: Phase = Phase.BIDDING_R1
        self.hands: list[list[Card]] = [[], [], [], []]
        self.kitty: list[Card] = []
        self.upcard: Card | None = None
        self.initial_hands: dict[int, list[Card]] = {}
        self.bid_order: list[int] = []
        self.bid_index: int = 0
        self.bid_decisions: list[BidDecision] = []
        self.round2_excluded: Suit | None = None
        self.trump: Suit | None = None
        self.trump_caller: int = -1
        self.going_alone: bool = False
        self.active_seats: list[int] = [0, 1, 2, 3]
        self.trick_num: int = 0
        self.leader: int = 1
        self.current_trick: list[tuple[int, Card]] = []
        self.trick_counts: list[int] = [0, 0]
        self.card_plays: list[CardPlay] = []
        self.point_delta: list[int] = [0, 0]
        self.grade_report_data: dict | None = None
        self._last_hand_record: HandRecord | None = None
        self.action_log: list[str] = []
        self.hand_log: list[str] = []       # full hand event history (persists between actions)
        self.completed_tricks: list[dict] = []
        self._error: str | None = None
        # Trick-complete display
        self.last_trick_plays: list[tuple[int, Card]] = []
        self.last_trick_winner: int = -1
        self.last_trick_explanation: str = ""
        self._pending_hand_complete: bool = False
        self.played_cards: list[tuple[int, Card]] = []   # (seat, Card) for all completed tricks
        self.played_tricks: list[list[tuple[int, Card]]] = []  # per-trick raw plays in order

    @classmethod
    def new(cls) -> "WebGameSession":
        session = cls(str(uuid.uuid4()))
        session._start_new_hand()
        return session

    def _log(self, msg: str) -> None:
        """Append to both the per-action log and the persistent hand log."""
        self.action_log.append(msg)
        self.hand_log.append(msg)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process_action(self, action: dict) -> dict:
        self.last_active = time.time()
        self.action_log = []
        self._error = None

        atype = action.get("type", "")

        if atype == "BID_R1" and self.phase == Phase.BIDDING_R1:
            self._process_bid_r1(action.get("choice", "pass"), bool(action.get("alone", False)))
        elif atype == "BID_R2" and self.phase == Phase.BIDDING_R2:
            self._process_bid_r2(action.get("choice", "pass"), bool(action.get("alone", False)))
        elif atype == "DISCARD" and self.phase == Phase.DISCARDING:
            self._process_discard(action.get("card_id", ""))
        elif atype == "PLAY_CARD" and self.phase == Phase.PLAYING_TRICK:
            self._process_play_card(action.get("card_id", ""))
        elif atype == "NEXT_TRICK" and self.phase == Phase.TRICK_COMPLETE:
            self._process_next_trick()
        elif atype == "REQUEST_GRADE" and self.phase == Phase.HAND_COMPLETE:
            self._process_request_grade()
        elif atype == "NEXT_HAND" and self.phase == Phase.HAND_COMPLETE:
            self._process_next_hand()
        elif atype == "NEW_GAME" and self.phase == Phase.GAME_OVER:
            self._process_new_game()
        else:
            self._error = f"Invalid action '{atype}' for phase '{self.phase.value}'"

        return self.to_state_dict()

    def to_state_dict(self) -> dict:
        legal = self._get_legal_plays()
        bid_seat = None
        if self.phase in (Phase.BIDDING_R1, Phase.BIDDING_R2) and self.bid_index < 4:
            bid_seat = self.bid_order[self.bid_index]

        opp_hands = {}
        for seat in [1, 2, 3]:
            opp_hands[str(seat)] = {
                "seat": seat,
                "name": PLAYER_NAMES[seat],
                "card_count": len(self.hands[seat]),
                "is_active": seat in self.active_seats,
            }

        trick_data = [
            {"seat": s, "seat_name": PLAYER_NAMES[s], "card": _serialize_card(c)}
            for s, c in self.current_trick
        ]

        trick_winner_seat = None
        if self.phase == Phase.TRICK_COMPLETE:
            trick_winner_seat = self.last_trick_winner

        last_trick_data = None
        if self.phase == Phase.TRICK_COMPLETE:
            last_trick_data = {
                "plays": [
                    {"seat": s, "seat_name": PLAYER_NAMES[s], "card": _serialize_card(c)}
                    for s, c in self.last_trick_plays
                ],
                "winner_seat": self.last_trick_winner,
                "winner_name": PLAYER_NAMES[self.last_trick_winner],
                "explanation": self.last_trick_explanation,
            }

        return {
            "session_id": self.session_id,
            "phase": self.phase.value,
            "scores": self.scores,
            "hand_number": self.hand_number,
            "dealer": self.dealer,
            "dealer_name": PLAYER_NAMES[self.dealer],
            "trump": self.trump.value if self.trump else None,
            "trump_symbol": SUIT_SYMBOLS[self.trump] if self.trump else None,
            "trump_caller": self.trump_caller,
            "going_alone": self.going_alone,
            "upcard": _serialize_card(self.upcard) if self.upcard else None,
            "bid_round": 1 if self.phase == Phase.BIDDING_R1 else (2 if self.phase == Phase.BIDDING_R2 else None),
            "bid_seat": bid_seat,
            "bid_seat_name": PLAYER_NAMES[bid_seat] if bid_seat is not None else None,
            "can_pass_r2": self._can_pass_r2(),
            "excluded_suit": self.round2_excluded.value if self.round2_excluded else None,
            "your_hand": [_serialize_card(c) for c in self.hands[HUMAN_SEAT]],
            "legal_plays": [_serialize_card(c) for c in legal],
            "legal_ids": [_serialize_card(c)["id"] for c in legal],
            "current_trick": trick_data,
            "trick_winner_seat": trick_winner_seat,
            "last_trick": last_trick_data,
            "trick_num": self.trick_num,
            "trick_counts": self.trick_counts,
            "leader": self.leader,
            "opponent_hands": opp_hands,
            "point_delta": self.point_delta,
            "grade_report": self.grade_report_data,
            "hint": self._get_hint(),
            "error": self._error,
            "action_log": self.action_log,
            "hand_log": self.hand_log,
            "completed_tricks": self.completed_tricks,
            "team_names": TEAM_NAMES,
        }

    # ------------------------------------------------------------------
    # Action handlers
    # ------------------------------------------------------------------

    def _process_bid_r1(self, choice: str, alone: bool) -> None:
        self._record_bid(round=1, seat=HUMAN_SEAT, choice=choice, alone=alone)
        if choice == "order":
            self._log("You order up")
            self._set_trump(self.upcard.suit, HUMAN_SEAT, alone)
            self._handle_dealer_pickup()
            if self.phase != Phase.DISCARDING:
                self._run_ai_until_human()
        else:
            self._log("You pass")
            self.bid_index += 1
            self._run_ai_until_human()

    def _process_bid_r2(self, choice: str, alone: bool) -> None:
        if choice == "pass" and HUMAN_SEAT == self.dealer:
            self._error = "You must call a suit as the dealer (stick the dealer rule)"
            return
        if choice != "pass":
            try:
                suit = Suit(choice)
            except ValueError:
                self._error = f"Unknown suit '{choice}'"
                return
        self._record_bid(round=2, seat=HUMAN_SEAT, choice=choice, alone=alone)
        if choice != "pass":
            self._log(f"You call {Suit(choice).name}")
            self._set_trump(Suit(choice), HUMAN_SEAT, alone)
            self._setup_trick_phase()
            self._run_ai_until_human()
        else:
            self._log("You pass")
            self.bid_index += 1
            self._run_ai_until_human()

    def _process_discard(self, card_id: str) -> None:
        card = _deserialize_card(card_id)
        if card is None or card not in self.hands[HUMAN_SEAT]:
            self._error = "Invalid card to discard"
            return
        self.hands[HUMAN_SEAT].remove(card)
        self._log("You discard a card")
        self._setup_trick_phase()
        self._run_ai_until_human()

    def _process_play_card(self, card_id: str) -> None:
        card = _deserialize_card(card_id)
        if card is None or card not in self.hands[HUMAN_SEAT]:
            self._error = "That card is not in your hand"
            return
        lead_card = self.current_trick[0][1] if self.current_trick else None
        legal = legal_plays(self.hands[HUMAN_SEAT], lead_card, self.trump)
        if card not in legal:
            self._error = "That card is not legal to play"
            return

        self.card_plays.append(CardPlay(
            trick_num=self.trick_num,
            seat=HUMAN_SEAT,
            hand_at_time=list(self.hands[HUMAN_SEAT]),
            trick_so_far=list(self.current_trick),
            tricks_won_at_time=list(self.trick_counts),
            trump=self.trump,
            caller=self.trump_caller,
            going_alone=self.going_alone,
            human_card=card,
            played_cards_at_time=list(self.played_cards),
            all_hands_at_time={seat: list(self.hands[seat]) for seat in range(4)},
            trump_void_seats=self._compute_trump_voids(),
        ))
        self.hands[HUMAN_SEAT].remove(card)
        self.current_trick.append((HUMAN_SEAT, card))
        self._log(f"You play {card.display(True)}")

        if len(self.current_trick) == len(self.active_seats):
            self._complete_trick()

        self._run_ai_until_human()

    def _process_next_trick(self) -> None:
        self.current_trick = []
        if self._pending_hand_complete:
            self._pending_hand_complete = False
            self._complete_hand()
        else:
            self.phase = Phase.PLAYING_TRICK
            self._run_ai_until_human()

    def _process_request_grade(self) -> None:
        if self._last_hand_record:
            from euchre.grader import MoveGrader
            report = MoveGrader().grade_hand(self._last_hand_record)
            self.grade_report_data = self._serialize_grade_report(report)

    def _process_next_hand(self) -> None:
        self.dealer = (self.dealer + 1) % 4
        self.hand_number += 1
        self.grade_report_data = None
        self._start_new_hand()

    def _process_new_game(self) -> None:
        self.scores = [0, 0]
        self.dealer = 0
        self.hand_number = 1
        self.hand_history = []
        self.grade_report_data = None
        self._last_hand_record = None
        self._start_new_hand()

    # ------------------------------------------------------------------
    # AI auto-run loop
    # ------------------------------------------------------------------

    def _run_ai_until_human(self) -> None:
        for _ in range(200):  # safety cap
            if self.phase == Phase.BIDDING_R1:
                if self.bid_index >= 4:
                    self._start_bidding_r2()
                    continue
                seat = self.bid_order[self.bid_index]
                if seat == HUMAN_SEAT:
                    return
                self._ai_bid_r1(seat)

            elif self.phase == Phase.BIDDING_R2:
                if self.bid_index >= 4:
                    # Shouldn't happen (stick-the-dealer), but redeal defensively
                    self._start_new_hand()
                    return
                seat = self.bid_order[self.bid_index]
                if seat == HUMAN_SEAT:
                    return
                self._ai_bid_r2(seat)

            elif self.phase == Phase.PLAYING_TRICK:
                next_seat = self._next_trick_seat()
                if next_seat == HUMAN_SEAT:
                    return
                self._ai_play(next_seat)

            else:
                return  # DISCARDING, HAND_COMPLETE, GAME_OVER — human acts

    # ------------------------------------------------------------------
    # AI bid helpers
    # ------------------------------------------------------------------

    def _ai_bid_r1(self, seat: int) -> None:
        choice, alone = ai.bid_decision(
            hand=self.hands[seat], round=1, dealer=self.dealer, seat=seat,
            upcard=self.upcard, score=list(self.scores),
        )
        self._record_bid(round=1, seat=seat, choice=choice, alone=alone)
        if choice == "order":
            alone_str = " and goes alone!" if alone else ""
            self._log(f"{PLAYER_NAMES[seat]} orders up{alone_str}")
            self._set_trump(self.upcard.suit, seat, alone)
            self._handle_dealer_pickup()
        else:
            self._log(f"{PLAYER_NAMES[seat]} passes")
            self.bid_index += 1

    def _ai_bid_r2(self, seat: int) -> None:
        choice, alone = ai.bid_decision(
            hand=self.hands[seat], round=2, dealer=self.dealer, seat=seat,
            excluded_suit=self.round2_excluded, score=list(self.scores),
        )
        self._record_bid(round=2, seat=seat, choice=choice, alone=alone)
        if choice != "pass":
            alone_str = " and goes alone!" if alone else ""
            self._log(f"{PLAYER_NAMES[seat]} calls {Suit(choice).name}{alone_str}")
            self._set_trump(Suit(choice), seat, alone)
            self._setup_trick_phase()
        else:
            self._log(f"{PLAYER_NAMES[seat]} passes")
            self.bid_index += 1

    def _ai_play(self, seat: int) -> None:
        lead_card = self.current_trick[0][1] if self.current_trick else None
        card, _tag = ai.card_to_play(
            hand=self.hands[seat],
            trick=self.current_trick,
            trump=self.trump,
            seat=seat,
            caller=self.trump_caller,
            going_alone=self.going_alone,
            played_cards=self.played_cards,
            trump_void_seats=self._compute_trump_voids(),
        )
        self.hands[seat].remove(card)
        self.current_trick.append((seat, card))
        self._log(f"{PLAYER_NAMES[seat]} plays {card.display(True)}")

        if len(self.current_trick) == len(self.active_seats):
            self._complete_trick()

    # ------------------------------------------------------------------
    # State transition helpers
    # ------------------------------------------------------------------

    def _record_bid(self, *, round: int, seat: int, choice: str, alone: bool) -> None:
        self.bid_decisions.append(BidDecision(
            round=round, seat=seat,
            hand_at_time=list(self.hands[seat]),
            upcard=self.upcard,
            excluded_suit=self.round2_excluded,
            score_at_time=list(self.scores),
            human_choice=choice,
            human_alone=alone,
            dealer=self.dealer,
        ))

    def _set_trump(self, trump: Suit, caller: int, going_alone: bool) -> None:
        self.trump = trump
        self.trump_caller = caller
        self.going_alone = going_alone
        if going_alone:
            sitting_out = partner_of(caller)
            self.active_seats = [s for s in [0, 1, 2, 3] if s != sitting_out]
        else:
            self.active_seats = [0, 1, 2, 3]

    def _handle_dealer_pickup(self) -> None:
        self.hands[self.dealer].append(self.upcard)
        if self.dealer == HUMAN_SEAT:
            self.phase = Phase.DISCARDING
        else:
            non_trumps = [c for c in self.hands[self.dealer] if not c.is_trump(self.trump)]
            if non_trumps:
                discard = min(non_trumps, key=lambda c: c.effective_rank(self.trump))
            else:
                discard = min(self.hands[self.dealer], key=lambda c: c.effective_rank(self.trump))
            self.hands[self.dealer].remove(discard)
            self._log(f"{PLAYER_NAMES[self.dealer]} discards a card")
            self._setup_trick_phase()

    def _start_bidding_r2(self) -> None:
        self.phase = Phase.BIDDING_R2
        self.round2_excluded = self.upcard.suit
        self.bid_index = 0
        self._log("All passed — naming a suit")

    def _setup_trick_phase(self) -> None:
        self.phase = Phase.PLAYING_TRICK
        self.trick_num = 0
        self.current_trick = []
        self.trick_counts = [0, 0]
        self.card_plays = []
        raw_leader = (self.dealer + 1) % 4
        if raw_leader in self.active_seats:
            self.leader = raw_leader
        else:
            for i in range(1, 5):
                candidate = (raw_leader + i) % 4
                if candidate in self.active_seats:
                    self.leader = candidate
                    break
        suit_sym = SUIT_SYMBOLS[self.trump] if self.trump else ""
        self._log(f"Trump: {self.trump.name} {suit_sym} — called by {PLAYER_NAMES[self.trump_caller]}")

    def _next_trick_seat(self) -> int:
        leader_pos = self.active_seats.index(self.leader)
        n = len(self.active_seats)
        return self.active_seats[(leader_pos + len(self.current_trick)) % n]

    def _complete_trick(self) -> None:
        winner = trick_winner(self.current_trick, self.trump)
        explanation = self._win_explanation(self.current_trick, self.trump, winner)
        self.played_cards.extend(self.current_trick)
        self.played_tricks.append(list(self.current_trick))
        self.trick_counts[team_of(winner)] += 1
        self._log(f"{PLAYER_NAMES[winner]} wins the trick ({self.trick_counts[0]}–{self.trick_counts[1]})")

        # Store for TRICK_COMPLETE display (don't clear current_trick yet)
        self.last_trick_plays = list(self.current_trick)
        self.last_trick_winner = winner
        self.last_trick_explanation = explanation

        # Persist to sidebar history
        self.completed_tricks.append({
            "trick_num": self.trick_num,
            "plays": [
                {"seat": s, "seat_name": PLAYER_NAMES[s], "card": _serialize_card(c)}
                for s, c in self.current_trick
            ],
            "winner_seat": winner,
            "winner_name": PLAYER_NAMES[winner],
            "explanation": explanation,
        })

        self.leader = winner
        self.trick_num += 1
        self._pending_hand_complete = (self.trick_num >= 5)
        self.phase = Phase.TRICK_COMPLETE

    @staticmethod
    def _win_explanation(trick: list[tuple[int, Card]], trump: Suit, winner_seat: int) -> str:
        from euchre.rules import is_right_bower, is_left_bower, effective_suit
        winner_card = next(c for s, c in trick if s == winner_seat)

        if is_right_bower(winner_card, trump):
            return "Right bower wins — the highest card in Euchre, always takes the trick."
        if is_left_bower(winner_card, trump):
            return "Left bower wins — second highest card, beats all trump except the right bower."
        if winner_card.is_trump(trump):
            other_trumps = [c for s, c in trick if c.is_trump(trump) and s != winner_seat]
            if other_trumps:
                return f"Highest trump wins — multiple trump were played, this one ranked highest."
            return "Only trump played — any trump card automatically beats all non-trump."

        led_suit = effective_suit(trick[0][1], trump)
        return (
            f"Highest {led_suit.name.capitalize()} wins — "
            f"no one played trump, so the top card of the led suit takes it."
        )

    def _complete_hand(self) -> None:
        caller_team = team_of(self.trump_caller)
        pts = hand_points(self.trick_counts, caller_team, self.going_alone)
        self.point_delta = pts
        for t in range(2):
            self.scores[t] += pts[t]

        record = HandRecord(
            dealer=self.dealer, trump=self.trump, trump_caller=self.trump_caller,
            going_alone=self.going_alone, initial_hands=self.initial_hands,
            bid_decisions=self.bid_decisions, card_plays=self.card_plays,
            hand_scores=list(self.trick_counts), point_delta=list(pts),
        )
        self.hand_history.append(record)
        self._last_hand_record = record

        if pts[0] > 0:
            self._log(f"Your team scores {pts[0]} point(s)!")
        else:
            self._log(f"Opponents score {pts[1]} point(s).")

        if max(self.scores) >= 10:
            self.phase = Phase.GAME_OVER
        else:
            self.phase = Phase.HAND_COMPLETE

    def _start_new_hand(self) -> None:
        deck = Deck()
        hands, kitty = deck.deal()
        self.hands = [list(h) for h in hands]
        self.kitty = kitty
        self.upcard = kitty[0]
        self.initial_hands = {i: list(self.hands[i]) for i in range(4)}
        self.trump = None
        self.trump_caller = -1
        self.going_alone = False
        self.active_seats = [0, 1, 2, 3]
        self.bid_order = [(self.dealer + 1 + i) % 4 for i in range(4)]
        self.bid_index = 0
        self.bid_decisions = []
        self.round2_excluded = None
        self.trick_num = 0
        self.leader = (self.dealer + 1) % 4
        self.current_trick = []
        self.trick_counts = [0, 0]
        self.card_plays = []
        self.point_delta = [0, 0]
        self.grade_report_data = None
        self._error = None
        self.last_trick_plays = []
        self.last_trick_winner = -1
        self.last_trick_explanation = ""
        self._pending_hand_complete = False
        self.completed_tricks = []
        self.played_cards = []
        self.played_tricks = []
        self.action_log = []
        self.hand_log = []
        self._log(f"Hand {self.hand_number} — Dealer: {PLAYER_NAMES[self.dealer]}")
        self.phase = Phase.BIDDING_R1
        self._run_ai_until_human()

    # ------------------------------------------------------------------
    # Utility helpers for to_state_dict
    # ------------------------------------------------------------------

    def _get_legal_plays(self) -> list[Card]:
        if self.phase != Phase.PLAYING_TRICK or not self.trump:
            return []
        if self._next_trick_seat() != HUMAN_SEAT:
            return []
        lead_card = self.current_trick[0][1] if self.current_trick else None
        return legal_plays(self.hands[HUMAN_SEAT], lead_card, self.trump)

    def _can_pass_r2(self) -> bool:
        if self.phase != Phase.BIDDING_R2:
            return True
        if self.bid_index >= 4:
            return True
        current_seat = self.bid_order[self.bid_index]
        return not (current_seat == HUMAN_SEAT and current_seat == self.dealer)

    def _get_hint(self) -> dict | None:
        if self.phase == Phase.PLAYING_TRICK:
            if not self.trump or self._next_trick_seat() != HUMAN_SEAT:
                return None
            return self._get_play_hint()
        if self.phase in (Phase.BIDDING_R1, Phase.BIDDING_R2):
            if self.bid_index >= 4 or self.bid_order[self.bid_index] != HUMAN_SEAT:
                return None
            return self._get_bid_hint()
        return None

    def _get_play_hint(self) -> dict:
        card, tag = ai.card_to_play(
            hand=self.hands[HUMAN_SEAT],
            trick=self.current_trick,
            trump=self.trump,
            seat=HUMAN_SEAT,
            caller=self.trump_caller,
            going_alone=self.going_alone,
            played_cards=self.played_cards,
            trump_void_seats=self._compute_trump_voids(),
        )
        from euchre.grader import EXPLANATIONS
        base = EXPLANATIONS.get(tag, tag)
        extra = _PLAY_HINT_CONTEXT.get(tag)
        explanation = base + (" " + " ".join(extra) if extra else "")
        tracking = self._build_card_tracking()
        if tracking:
            explanation += "\n\n" + tracking
        return {
            "type": "play",
            "card": _serialize_card(card),
            "display": f"Play {card.display(True)}",
            "action": None,
            "alone": None,
            "explanation": explanation,
            "tag": tag,
        }

    def _compute_trump_voids(self) -> frozenset[int]:
        """Return seats confirmed void in trump: any seat that failed to follow a trump lead."""
        if not self.trump:
            return frozenset()
        voids: set[int] = set()
        for trick in self.played_tricks:
            if not trick:
                continue
            _, led_card = trick[0]
            if led_card.is_trump(self.trump):
                for seat, card in trick[1:]:
                    if not card.is_trump(self.trump):
                        voids.add(seat)
        return frozenset(voids)

    def _compute_voids(self) -> dict[int, set]:
        """Infer confirmed suit voids from play history: if a player didn't follow the led suit, they're void."""
        from euchre.rules import effective_suit as eff_suit
        voids: dict[int, set] = {1: set(), 2: set(), 3: set()}
        for trick in self.played_tricks:
            if not trick:
                continue
            _, led_card = trick[0]
            led_eff = eff_suit(led_card, self.trump)
            for seat, card in trick[1:]:
                if seat not in voids:
                    continue
                if eff_suit(card, self.trump) != led_eff:
                    voids[seat].add(led_eff)
        return voids

    def _build_card_tracking(self) -> str:
        if not self.trump:
            return ""
        # All cards visible to the human: completed tricks + plays already made in current trick
        seen: list[tuple[int, Card]] = list(self.played_cards) + list(self.current_trick)
        if not seen:
            return ""

        voids = self._compute_voids()

        # Also infer voids from current (incomplete) trick
        from euchre.rules import effective_suit as eff_suit
        if len(self.current_trick) > 1:
            _, led_card = self.current_trick[0]
            led_eff = eff_suit(led_card, self.trump)
            for seat, card in self.current_trick[1:]:
                if seat in voids and eff_suit(card, self.trump) != led_eff:
                    voids[seat].add(led_eff)

        trump_plays = [(s, c) for s, c in seen if c.is_trump(self.trump)]
        right_play = next(((s, c) for s, c in seen if is_right_bower(c, self.trump)), None)
        left_play  = next(((s, c) for s, c in seen if is_left_bower(c, self.trump)), None)

        # Trump accounting
        total_trump = 7  # right bower + left bower + A,K,Q,10,9 of trump suit
        human_trump_count = sum(1 for c in self.hands[HUMAN_SEAT] if c.is_trump(self.trump))
        played_trump_count = len(trump_plays)
        unaccounted = total_trump - human_trump_count - played_trump_count

        lines: list[str] = []

        # ── Trump status ──────────────────────────────────────────────────────
        trump_sym = SUIT_SYMBOLS[self.trump]
        trump_name = self.trump.name.capitalize()
        tparts = []
        if right_play:
            tparts.append(f"Right bower: played by {PLAYER_NAMES[right_play[0]]}")
        else:
            tparts.append("Right bower: still unplayed")
        if left_play:
            tparts.append(f"Left bower: played by {PLAYER_NAMES[left_play[0]]}")
        else:
            tparts.append("Left bower: still unplayed")
        tparts.append(
            f"{played_trump_count} of {total_trump} trump seen in tricks; "
            f"{unaccounted} unaccounted for (in opponents' hands or kitty)"
        )
        lines.append(f"Trump ({trump_name} {trump_sym}): " + " | ".join(tparts) + ".")

        # ── Confirmed voids ───────────────────────────────────────────────────
        void_notes = []
        for seat in [1, 2, 3]:
            if voids[seat]:
                label = "Partner" if seat == partner_of(HUMAN_SEAT) else PLAYER_NAMES[seat]
                suit_names = ", ".join(s.name.capitalize() for s in sorted(voids[seat], key=lambda s: s.value))
                void_notes.append(f"{label} void in {suit_names}")
        if void_notes:
            lines.append("Confirmed voids: " + "; ".join(void_notes) + ".")

        # ── Per-player hand summary ───────────────────────────────────────────
        lines.append("Hands:")
        for seat in [1, 2, 3]:
            cards_played_by = [c for s, c in seen if s == seat]
            cards_left = len(self.initial_hands.get(seat, [])) - len(cards_played_by)
            trump_shown = [c for c in cards_played_by if c.is_trump(self.trump)]
            is_partner = (seat == partner_of(HUMAN_SEAT))
            label = "Partner" if is_partner else PLAYER_NAMES[seat]

            played_str = (
                ", ".join(c.display(True) for c in cards_played_by)
                if cards_played_by else "nothing"
            )
            if trump_shown:
                trump_note = f"showed trump ({', '.join(c.display(True) for c in trump_shown)})"
            elif self.trump in voids.get(seat, set()):
                trump_note = "confirmed void in trump"
            else:
                trump_note = "trump status unknown"

            player_voids = voids.get(seat, set()) - {self.trump}
            void_note = (
                f"; void in {', '.join(s.name.capitalize() for s in sorted(player_voids, key=lambda s: s.value))}"
                if player_voids else ""
            )
            lines.append(f"  {label} ({cards_left} left): played {played_str}; {trump_note}{void_note}.")

        # ── Forward-looking inference ─────────────────────────────────────────
        insights = []

        # Right bower inference
        if not right_play:
            # Which opponents could still hold the right bower?
            candidates = [
                s for s in [1, 2, 3]
                if self.trump not in voids.get(s, set())  # not trump-void
                and (len(self.initial_hands.get(s, [])) - len([c for ss, c in seen if ss == s])) > 0
            ]
            if len(candidates) == 1:
                label = "Partner" if candidates[0] == partner_of(HUMAN_SEAT) else PLAYER_NAMES[candidates[0]]
                insights.append(
                    f"Right bower still out — all other opponents are trump-void, "
                    f"so {label} likely holds it (or it's in the kitty)."
                )
            elif candidates:
                labels = [("Partner" if s == partner_of(HUMAN_SEAT) else PLAYER_NAMES[s]) for s in candidates]
                insights.append(
                    f"Right bower still out — could be with {', '.join(labels)}, or in the kitty."
                )

        # Left bower inference
        if not left_play:
            candidates = [
                s for s in [1, 2, 3]
                if self.trump not in voids.get(s, set())
                and (len(self.initial_hands.get(s, [])) - len([c for ss, c in seen if ss == s])) > 0
            ]
            if len(candidates) == 1:
                label = "Partner" if candidates[0] == partner_of(HUMAN_SEAT) else PLAYER_NAMES[candidates[0]]
                insights.append(
                    f"Left bower still out — {label} likely holds it (or kitty)."
                )

        # Flag trump-heavy opponents
        for seat in [1, 2, 3]:
            trump_count_seen = len([c for s, c in seen if s == seat and c.is_trump(self.trump)])
            cards_left = len(self.initial_hands.get(seat, [])) - len([c for s, c in seen if s == seat])
            if trump_count_seen == 0 and self.trump not in voids.get(seat, set()) and cards_left > 0 and unaccounted > 0:
                label = "Partner" if seat == partner_of(HUMAN_SEAT) else PLAYER_NAMES[seat]
                insights.append(
                    f"{label} has shown no trump yet with {cards_left} cards left — "
                    f"they may still be holding trump."
                )

        if insights:
            lines.append("Inference: " + " ".join(insights))

        return "\n".join(lines)

    def _get_bid_hint(self) -> dict:
        if self.phase == Phase.BIDDING_R1:
            return self._build_bid_r1_hint()
        return self._build_bid_r2_hint()

    def _build_bid_r1_hint(self) -> dict:
        hand = self.hands[HUMAN_SEAT]
        trump = self.upcard.suit
        score = ai._score_hand_for_trump(hand, trump)
        is_dealer = (HUMAN_SEAT == self.dealer)
        is_dealers_partner = (HUMAN_SEAT == partner_of(self.dealer))
        threshold = 5.0
        if is_dealer:
            threshold = 4.5
        elif is_dealers_partner:
            threshold -= 0.5

        action, alone = ai.bid_decision(
            hand=hand, round=1, dealer=self.dealer, seat=HUMAN_SEAT,
            upcard=self.upcard, score=list(self.scores),
        )

        trump_cards = [c for c in hand if c.effective_suit(trump) == trump]
        trump_count = len(trump_cards)
        has_right = any(is_right_bower(c, trump) for c in hand)
        has_left = any(is_left_bower(c, trump) for c in hand)
        parts = []
        if has_right:
            parts.append("the right bower")
        if has_left:
            parts.append("the left bower")
        other = trump_count - (1 if has_right else 0) - (1 if has_left else 0)
        if other == 1:
            parts.append("1 other trump")
        elif other > 1:
            parts.append(f"{other} other trump")
        hand_desc = ", ".join(parts) if parts else "no trump"

        suit_name = trump.name.capitalize()
        sym = SUIT_SYMBOLS[trump]

        if action == "order":
            display = f"Order Up ({suit_name} {sym})"
            s1 = f"Order up {suit_name} {sym}."
            s2 = f"Your hand scores {score:.1f} for {suit_name} trump — you hold {hand_desc}."
            alone_note = " Going alone is recommended with this powerful hand." if alone else ""
            s3 = f"The ordering threshold here is {threshold:.1f}; your score of {score:.1f} clears it.{alone_note}"
        else:
            display = "Pass"
            s1 = f"Pass — {suit_name} {sym} is not strong enough to order up."
            s2 = f"Your hand scores {score:.1f} for {suit_name} trump — you hold {hand_desc}."
            s3 = f"The ordering threshold here is {threshold:.1f}; your score falls short, so wait for round 2 to potentially name a stronger suit."

        return {
            "type": "bid",
            "card": None,
            "display": display,
            "action": action,
            "alone": alone,
            "explanation": f"{s1} {s2} {s3}",
            "tag": "BID_HINT_ORDER" if action == "order" else "BID_HINT_PASS",
        }

    def _build_bid_r2_hint(self) -> dict:
        hand = self.hands[HUMAN_SEAT]
        excluded = self.round2_excluded
        is_dealer = (HUMAN_SEAT == self.dealer)

        action, alone = ai.bid_decision(
            hand=hand, round=2, dealer=self.dealer, seat=HUMAN_SEAT,
            excluded_suit=excluded, score=list(self.scores),
        )

        best_suit, best_score = ai._best_suit_for_round2(hand, excluded)

        if action == "pass":
            display = "Pass"
            s1 = "Pass — no available suit is strong enough to call."
            s2 = f"Your best option is {best_suit.name.capitalize()} with a score of {best_score:.1f}, which falls below the 5.0 threshold."
            s3 = "With a weak hand in round 2, it is better to give opponents the risky call than to name a weak trump yourself."
            tag = "BID_HINT_PASS"
        else:
            suit = Suit(action)
            sym = SUIT_SYMBOLS[suit]
            suit_name = suit.name.capitalize()
            trump_cards = [c for c in hand if c.effective_suit(suit) == suit]
            trump_count = len(trump_cards)
            has_right = any(is_right_bower(c, suit) for c in hand)
            has_left = any(is_left_bower(c, suit) for c in hand)
            parts = []
            if has_right:
                parts.append("the right bower")
            if has_left:
                parts.append("the left bower")
            other = trump_count - (1 if has_right else 0) - (1 if has_left else 0)
            if other == 1:
                parts.append("1 other trump")
            elif other > 1:
                parts.append(f"{other} other trump")
            hand_desc = ", ".join(parts) if parts else "some trump"
            alone_note = " Going alone is recommended with this powerful hand." if alone else ""
            display = f"Call {suit_name} {sym}"
            s1 = f"Call {suit_name} {sym} — it is your strongest available suit."
            s2 = f"You score {best_score:.1f} with {suit_name} trump: you hold {hand_desc}."
            if is_dealer and best_score < 5.0:
                s3 = f"As the dealer under stick-the-dealer, you must call a suit — {suit_name} is your best option.{alone_note}"
            else:
                s3 = f"This clears the 5.0 threshold for round 2.{alone_note}"
            tag = "BID_HINT_CALL"

        return {
            "type": "bid",
            "card": None,
            "display": display,
            "action": action,
            "alone": alone,
            "explanation": f"{s1} {s2} {s3}",
            "tag": tag,
        }

    # ------------------------------------------------------------------
    # Grade report serialization
    # ------------------------------------------------------------------

    def _serialize_grade_report(self, report) -> dict:
        def fmt_bid_choice(choice: str) -> str:
            if choice == "order":
                return "Order Up"
            if choice == "pass":
                return "Pass"
            try:
                return f"Call {Suit(choice).name}"
            except ValueError:
                return choice

        hand_scores_out = {
            str(seat): {"name": PLAYER_NAMES[seat], "score": score}
            for seat, score in report.hand_scores.items()
        }
        return {
            "summary": report.summary,
            "narrative": report.narrative,
            "hand_scores": hand_scores_out,
            "bid_grades": [
                {
                    "round": g.decision.round,
                    "your_choice": fmt_bid_choice(g.decision.human_choice),
                    "your_alone": g.decision.human_alone,
                    "ai_action": fmt_bid_choice(g.ai_action),
                    "ai_alone": g.ai_alone,
                    "verdict": g.verdict,
                    "explanation": g.explanation,
                }
                for g in report.bid_grades
            ],
            "play_grades": [
                {
                    "trick_num": g.play.trick_num + 1,
                    "your_card": _serialize_card(g.play.human_card),
                    "ai_card": _serialize_card(g.ai_card),
                    "verdict": g.verdict,
                    "explanation": g.explanation,
                    "counterfactual": g.counterfactual_note,
                }
                for g in report.play_grades
            ],
        }
