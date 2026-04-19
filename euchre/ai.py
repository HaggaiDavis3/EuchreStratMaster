from __future__ import annotations
from euchre.cards import Card, Rank, Suit
from euchre.rules import (
    effective_suit, effective_rank, is_right_bower, is_left_bower,
    legal_plays, trick_winner, partner_of, team_of,
)


# ---------------------------------------------------------------------------
# Hand scoring for bidding
# ---------------------------------------------------------------------------

def _score_hand_for_trump(hand: list[Card], trump: Suit) -> float:
    score = 0.0
    trump_count = 0
    for card in hand:
        if is_right_bower(card, trump):
            score += 5
            trump_count += 1
        elif is_left_bower(card, trump):
            score += 4
            trump_count += 1
        elif card.effective_suit(trump) == trump:
            trump_count += 1
            if card.rank == Rank.ACE:
                score += 3
            elif card.rank == Rank.KING:
                score += 2
            elif card.rank == Rank.QUEEN:
                score += 1
            else:
                score += 0.5
        elif card.rank == Rank.ACE:
            score += 0.5  # off-suit ace
    # bonus for extra trump beyond 3
    if trump_count > 3:
        score += (trump_count - 3) * 1.0
    return score


def _best_suit_for_round2(hand: list[Card], excluded: Suit) -> tuple[Suit, float]:
    best_suit = None
    best_score = -1.0
    for suit in Suit:
        if suit == excluded:
            continue
        s = _score_hand_for_trump(hand, suit)
        if s > best_score:
            best_score = s
            best_suit = suit
    return best_suit, best_score  # type: ignore[return-value]


def _can_go_alone(hand: list[Card], trump: Suit, my_game_score: int = 0) -> bool:
    score = _score_hand_for_trump(hand, trump)
    # Lower the hand-strength bar when a march wins the game (4 pts needed from 6+)
    threshold = 7.0 if my_game_score >= 6 else 9.0
    if score < threshold:
        return False
    has_right = any(is_right_bower(c, trump) for c in hand)
    has_left = any(is_left_bower(c, trump) for c in hand)
    has_trump_ace = any(
        c.effective_suit(trump) == trump and c.rank == Rank.ACE
        and not is_right_bower(c, trump) and not is_left_bower(c, trump)
        for c in hand
    )
    return has_right and (has_left or has_trump_ace)


# ---------------------------------------------------------------------------
# Public bidding function
# ---------------------------------------------------------------------------

# Effective ranks of all 7 trump cards (right bower, left bower, A K Q 10 9)
_ALL_TRUMP_RANKS = frozenset({100, 99, 14, 13, 12, 10, 9})


def bid_decision(
    hand: list[Card],
    round: int,
    dealer: int,
    seat: int,
    upcard: Card | None = None,       # round 1: the turned-up card
    excluded_suit: Suit | None = None, # round 2: the turned-down suit
    score: list[int] | None = None,    # [team0_pts, team1_pts]
) -> tuple[str, bool]:
    """Return (action, going_alone).

    Round 1 actions: "order" | "pass"
    Round 2 actions: suit value string ("S","C","H","D") | "pass"
    going_alone is only True when action == "order" or a suit name.
    """
    my_team = team_of(seat)
    my_score = score[my_team] if score is not None else 0
    opp_score = score[1 - my_team] if score is not None else 0

    if round == 1:
        assert upcard is not None
        trump = upcard.suit
        score_val = _score_hand_for_trump(hand, trump)

        is_dealer = (seat == dealer)
        is_dealers_partner = (seat == partner_of(dealer))

        threshold = 5.0
        if is_dealer:
            threshold = 4.5
        elif is_dealers_partner:
            threshold -= 0.5

        # Score-aware adjustments
        if my_score >= 9:
            threshold -= 2.0   # need 1 pt to win — order with almost any trump hand
        elif my_score >= 7:
            threshold -= 0.5   # one good hand wins it
        if opp_score >= 9:
            threshold += 0.75  # getting euchred hands them the game

        if score_val >= threshold:
            alone = _can_go_alone(hand, trump, my_score)
            return ("order", alone)
        return ("pass", False)

    else:  # round 2
        assert excluded_suit is not None
        best_suit, best_score = _best_suit_for_round2(hand, excluded_suit)
        is_dealer = (seat == dealer)

        r2_threshold = 5.0
        if my_score >= 9:
            r2_threshold -= 2.0
        elif my_score >= 7:
            r2_threshold -= 0.5
        if opp_score >= 9:
            r2_threshold += 0.75

        if best_score >= r2_threshold or (is_dealer and best_score > 0):
            # Stick the dealer: dealer must call something
            alone = _can_go_alone(hand, best_suit, my_score)
            return (best_suit.value, alone)
        return ("pass", False)


# ---------------------------------------------------------------------------
# Card play helpers
# ---------------------------------------------------------------------------

def _trump_cards(hand: list[Card], trump: Suit) -> list[Card]:
    return [c for c in hand if c.is_trump(trump)]


def _non_trump(hand: list[Card], trump: Suit) -> list[Card]:
    return [c for c in hand if not c.is_trump(trump)]


def _highest(cards: list[Card], trump: Suit) -> Card:
    return max(cards, key=lambda c: effective_rank(c, trump))


def _lowest(cards: list[Card], trump: Suit) -> Card:
    return min(cards, key=lambda c: effective_rank(c, trump))


def _partner_currently_winning(trick: list[tuple[int, Card]], partner: int, trump: Suit) -> bool:
    if not trick:
        return False
    return trick_winner(trick, trump) == partner


def _current_best_card(trick: list[tuple[int, Card]], trump: Suit) -> Card:
    winner_seat = trick_winner(trick, trump)
    for seat, card in trick:
        if seat == winner_seat:
            return card
    return trick[0][1]  # fallback


def _lowest_winner(legal: list[Card], trick: list[tuple[int, Card]], trump: Suit) -> Card | None:
    """Return the lowest card in legal that beats the current best, or None.

    Prefers non-trump winners over trump winners to conserve trump.
    """
    if not trick:
        return None
    best_card = _current_best_card(trick, trump)
    best_rank = effective_rank(best_card, trump)
    best_is_trump = best_card.is_trump(trump)
    led_suit = effective_suit(trick[0][1], trump)

    def beats(card: Card) -> bool:
        if card.is_trump(trump):
            if best_is_trump:
                return effective_rank(card, trump) > best_rank
            return True  # any trump beats any non-trump
        if effective_suit(card, trump) == led_suit:
            if best_is_trump:
                return False  # non-trump never beats trump
            return effective_rank(card, trump) > best_rank
        return False

    winners = [c for c in legal if beats(c)]
    if not winners:
        return None
    # Prefer non-trump winners (saves trump); within each group, use lowest rank
    return min(winners, key=lambda c: (1 if c.is_trump(trump) else 0, effective_rank(c, trump)))


def _best_off_ace(hand: list[Card], trump: Suit) -> Card | None:
    aces = [c for c in hand if c.rank == Rank.ACE and not c.is_trump(trump)]
    return aces[0] if aces else None


# ---------------------------------------------------------------------------
# Public card play function
# ---------------------------------------------------------------------------

def card_to_play(
    hand: list[Card],
    trick: list[tuple[int, Card]],  # plays so far (empty if leading)
    trump: Suit,
    seat: int,
    caller: int,
    going_alone: bool = False,
    played_cards: list[tuple[int, Card]] | None = None,  # all completed-trick plays seen so far
    trump_void_seats: frozenset[int] | None = None,       # seats confirmed void in trump
) -> tuple[Card, str]:
    """Return (card_to_play, strategy_tag).

    strategy_tag is a string key used by the grader for explanations.
    """
    partner = partner_of(seat)
    legal = legal_plays(hand, trick[0][1] if trick else None, trump)
    trumps = _trump_cards(legal, trump)
    non_trumps = _non_trump(legal, trump)

    # Active opponents: used for void detection
    active_seats = [s for s in [0, 1, 2, 3] if not going_alone or s != partner_of(caller)]
    opponent_seats = [s for s in active_seats if team_of(s) != team_of(seat)]

    # --- LEADING ---
    if not trick:
        all_trumps = _trump_cards(hand, trump)
        has_right = any(is_right_bower(c, trump) for c in hand)
        has_left = any(is_left_bower(c, trump) for c in hand)
        defending = (team_of(caller) != team_of(seat))

        if has_right and has_left:
            right = next(c for c in hand if is_right_bower(c, trump))
            return right, "LEAD_BOTH_BOWERS"

        # Unbeatable trump: either all opponents are confirmed trump-void,
        # or every higher trump rank has already been played
        if trumps:
            all_opps_void = (
                trump_void_seats is not None
                and bool(opponent_seats)
                and all(s in trump_void_seats for s in opponent_seats)
            )
            outranked = False
            if played_cards is not None:
                played_trump_ranks = {
                    effective_rank(c, trump)
                    for _, c in played_cards
                    if c.is_trump(trump)
                }
                my_trump_ranks = {effective_rank(c, trump) for c in all_trumps}
                higher_unplayed = _ALL_TRUMP_RANKS - played_trump_ranks - my_trump_ranks
                outranked = not any(r > min(my_trump_ranks) for r in higher_unplayed)
            if all_opps_void or outranked:
                return _highest(trumps, trump), "LEAD_TRUMP_UNBEATABLE"

        off_ace = _best_off_ace(hand, trump)

        if defending:
            # Opponent called — establish side tricks before they run trump
            if off_ace:
                return off_ace, "LEAD_OFF_ACE_DEFENSE"
            if len(all_trumps) >= 3:
                return _highest(trumps, trump), "LEAD_TRUMP_POWER"
        else:
            # My team called — lead trump to establish control
            if len(all_trumps) >= 3:
                return _highest(trumps, trump), "LEAD_TRUMP_POWER"
            if caller == partner_of(seat) and off_ace:
                # Partner called — lead off-ace, let partner use trump later
                return off_ace, "LEAD_OFF_ACE_PARTNER_CALLED"
            if len(all_trumps) >= 2:
                # Caller with 2 trump — lead trump to flush opponents
                return _highest(trumps, trump), "LEAD_TRUMP_CALLER"

        if going_alone and trumps:
            return _highest(trumps, trump), "LEAD_TRUMP_ALONE"

        if non_trumps:
            return _highest(non_trumps, trump), "LEAD_HIGHEST_OFFSUIT"
        return _highest(trumps, trump), "LEAD_TRUMP_ONLY_OPTION"

    # --- FOLLOWING ---
    n_active = 3 if going_alone else 4
    is_last = len(trick) == n_active - 1
    is_second = len(trick) == 1

    partner_winning = _partner_currently_winning(trick, partner, trump)

    if partner_winning:
        # Partner has it — throw cheapest card
        if non_trumps:
            return _lowest(non_trumps, trump), "THROW_LOW_PARTNER_WINNING"
        return _lowest(trumps, trump), "THROW_LOW_TRUMP_PARTNER_WINNING"

    # Opponent is winning — try to take the trick
    winner_card = _lowest_winner(legal, trick, trump)

    # 2nd-seat heuristic: don't spend low trump when partner and 4th player haven't acted
    if (winner_card is not None
            and is_second and not is_last
            and winner_card.is_trump(trump)
            and not is_right_bower(winner_card, trump)
            and not is_left_bower(winner_card, trump)
            and non_trumps
            and team_of(trick[0][0]) != team_of(seat)):  # opponent led
        return _lowest(non_trumps, trump), "THROW_LOW_SECOND_SEAT"

    if winner_card:
        if is_last:
            return winner_card, "WIN_TRICK_LAST"
        return winner_card, "WIN_TRICK"

    # Can't win — throw cheapest non-trump, else cheapest trump
    if non_trumps:
        return _lowest(non_trumps, trump), "THROW_LOW_CANT_WIN"
    return _lowest(trumps, trump), "THROW_LOW_TRUMP_CANT_WIN"
