from __future__ import annotations
from euchre.cards import Card, Rank, Suit


def is_right_bower(card: Card, trump: Suit) -> bool:
    return card.rank == Rank.JACK and card.suit == trump


def is_left_bower(card: Card, trump: Suit) -> bool:
    return card.rank == Rank.JACK and card.suit == trump.same_color


def effective_suit(card: Card, trump: Suit) -> Suit:
    return card.effective_suit(trump)


def effective_rank(card: Card, trump: Suit) -> int:
    return card.effective_rank(trump)


def legal_plays(hand: list[Card], lead_card: Card | None, trump: Suit) -> list[Card]:
    """Return cards the player may legally play.

    Must follow the led suit if possible. Left bower follows the trump suit.
    If leading (lead_card is None), all cards are legal.
    """
    if lead_card is None:
        return list(hand)
    led_suit = effective_suit(lead_card, trump)
    followers = [c for c in hand if effective_suit(c, trump) == led_suit]
    return followers if followers else list(hand)


def trick_winner(plays: list[tuple[int, Card]], trump: Suit) -> int:
    """Return the seat index of the trick winner.

    plays: list of (seat, card) in play order; first entry is the leader.
    """
    led_suit = effective_suit(plays[0][1], trump)

    def card_power(seat_card: tuple[int, Card]) -> int:
        _, card = seat_card
        if card.is_trump(trump):
            return 1000 + effective_rank(card, trump)
        if effective_suit(card, trump) == led_suit:
            return effective_rank(card, trump)
        return 0  # off-suit, non-trump: can't win

    winner_seat, _ = max(plays, key=card_power)
    return winner_seat


def hand_points(
    tricks_won_by_team: list[int],
    caller_team: int,
    going_alone: bool,
) -> list[int]:
    """Return [team0_points, team1_points] earned this hand.

    tricks_won_by_team: [team0_tricks, team1_tricks]
    caller_team: 0 or 1
    """
    defender_team = 1 - caller_team
    caller_tricks = tricks_won_by_team[caller_team]
    points = [0, 0]

    if caller_tricks >= 3:
        if going_alone and caller_tricks == 5:
            points[caller_team] = 4
        elif caller_tricks == 5:
            points[caller_team] = 2
        else:
            points[caller_team] = 1
    else:
        # Euchred
        points[defender_team] = 2

    return points


def partner_of(seat: int) -> int:
    return (seat + 2) % 4


def team_of(seat: int) -> int:
    return seat % 2
