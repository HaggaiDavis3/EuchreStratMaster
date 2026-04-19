from __future__ import annotations
import random
from dataclasses import dataclass
from enum import Enum


class Suit(Enum):
    SPADES = "S"
    CLUBS = "C"
    HEARTS = "H"
    DIAMONDS = "D"

    @property
    def same_color(self) -> Suit:
        """Return the other suit of the same color (for bower logic)."""
        pairs = {
            Suit.SPADES: Suit.CLUBS,
            Suit.CLUBS: Suit.SPADES,
            Suit.HEARTS: Suit.DIAMONDS,
            Suit.DIAMONDS: Suit.HEARTS,
        }
        return pairs[self]


class Rank(Enum):
    NINE = 9
    TEN = 10
    JACK = 11
    QUEEN = 12
    KING = 13
    ACE = 14


SUIT_UNICODE = {Suit.SPADES: "♠", Suit.CLUBS: "♣", Suit.HEARTS: "♥", Suit.DIAMONDS: "♦"}
SUIT_ASCII   = {Suit.SPADES: "S", Suit.CLUBS: "C", Suit.HEARTS: "H", Suit.DIAMONDS: "D"}
RANK_DISPLAY = {
    Rank.NINE: "9", Rank.TEN: "10", Rank.JACK: "J",
    Rank.QUEEN: "Q", Rank.KING: "K", Rank.ACE: "A",
}

# Detected once at import time; ui.py may override after startup probe.
_USE_UNICODE = True


@dataclass(frozen=True)
class Card:
    rank: Rank
    suit: Suit

    def effective_suit(self, trump: Suit) -> Suit:
        """Left bower belongs to the trump suit for following/leading purposes."""
        if self.rank == Rank.JACK and self.suit == trump.same_color:
            return trump
        return self.suit

    def effective_rank(self, trump: Suit) -> int:
        """Right bower=100, left bower=99, else the rank's int value."""
        if self.rank == Rank.JACK:
            if self.suit == trump:
                return 100  # right bower
            if self.suit == trump.same_color:
                return 99   # left bower
        return self.rank.value

    def is_trump(self, trump: Suit) -> bool:
        return self.effective_suit(trump) == trump

    def display(self, use_unicode: bool = True) -> str:
        suit_map = SUIT_UNICODE if use_unicode else SUIT_ASCII
        return f"{RANK_DISPLAY[self.rank]}{suit_map[self.suit]}"

    def __str__(self) -> str:
        return self.display(_USE_UNICODE)

    def __repr__(self) -> str:
        return self.display(False)


class Deck:
    def __init__(self) -> None:
        self.cards: list[Card] = self.build()

    @staticmethod
    def build() -> list[Card]:
        return [Card(rank, suit) for suit in Suit for rank in Rank]

    def shuffle(self) -> None:
        random.shuffle(self.cards)

    def deal(self, n_players: int = 4, cards_each: int = 5) -> tuple[list[list[Card]], list[Card]]:
        """Return (hands, kitty). Kitty is the remaining cards."""
        self.shuffle()
        hands = [
            self.cards[i * cards_each:(i + 1) * cards_each]
            for i in range(n_players)
        ]
        kitty = self.cards[n_players * cards_each:]
        return hands, kitty
