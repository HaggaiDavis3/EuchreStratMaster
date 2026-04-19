from __future__ import annotations
import os
import sys
from euchre.cards import Card, Suit, Rank, SUIT_UNICODE, SUIT_ASCII, RANK_DISPLAY

try:
    from colorama import init as colorama_init, Fore, Style
    colorama_init(autoreset=True)
    _HAS_COLOR = True
except ImportError:
    _HAS_COLOR = False

    class _FakeColor:
        def __getattr__(self, _: str) -> str:
            return ""

    Fore = _FakeColor()    # type: ignore[assignment]
    Style = _FakeColor()   # type: ignore[assignment]


def _probe_unicode() -> bool:
    """Return True if the terminal encoding can display Unicode suit symbols."""
    encoding = getattr(sys.stdout, "encoding", "") or ""
    return encoding.lower().replace("-", "") in ("utf8", "utf16", "utf32")


RED_SUITS = {Suit.HEARTS, Suit.DIAMONDS}
VERDICT_COLOR = {
    "OPTIMAL": Fore.GREEN,
    "ACCEPTABLE": Fore.YELLOW,
    "MISTAKE": Fore.RED,
}


class UI:
    def __init__(self, use_color: bool = True) -> None:
        self._color = use_color and _HAS_COLOR
        self._unicode = _probe_unicode()

    # ------------------------------------------------------------------
    # Card display helpers
    # ------------------------------------------------------------------

    def _card_str(self, card: Card, highlight: bool = False, is_trump: bool = False) -> str:
        suit_map = SUIT_UNICODE if self._unicode else SUIT_ASCII
        s = f"{RANK_DISPLAY[card.rank]}{suit_map[card.suit]}"
        if self._color:
            if card.suit in RED_SUITS:
                s = Fore.RED + s + Style.RESET_ALL
            if is_trump:
                s = Style.BRIGHT + s + Style.RESET_ALL
            if highlight:
                s = Fore.CYAN + s + Style.RESET_ALL
        return s

    def _suit_str(self, suit: Suit) -> str:
        sym = (SUIT_UNICODE if self._unicode else SUIT_ASCII)[suit]
        if self._color and suit in RED_SUITS:
            return Fore.RED + sym + Style.RESET_ALL
        return sym

    # ------------------------------------------------------------------
    # Announce / clear
    # ------------------------------------------------------------------

    def announce(self, msg: str) -> None:
        print(msg)

    def clear_screen(self) -> None:
        os.system("cls" if os.name == "nt" else "clear")

    def welcome(self) -> None:
        self.clear_screen()
        print("=" * 60)
        print("         EUCHRE STRAT MASTER — Practice Mode")
        print("  You (South) & North vs West & East  |  Game to 10")
        print("=" * 60)

    def game_over(self, winner: str, scores: list[int]) -> None:
        print("\n" + "=" * 60)
        print(f"  GAME OVER — {winner} wins!")
        print(f"  Final score: {scores[0]} – {scores[1]}")
        print("=" * 60)

    # ------------------------------------------------------------------
    # Hand display
    # ------------------------------------------------------------------

    def show_upcard(self, card: Card) -> None:
        print(f"\nUpcard: {self._card_str(card)}")

    def show_hand(
        self,
        cards: list[Card],
        label: str = "Hand",
        trump: Suit | None = None,
        legal: list[Card] | None = None,
    ) -> None:
        parts = []
        for i, c in enumerate(cards, 1):
            is_trump = trump is not None and c.is_trump(trump)
            is_legal = legal is None or c in legal
            s = self._card_str(c, highlight=is_legal and legal is not None, is_trump=is_trump)
            parts.append(f"[{i}]{s}")
        if legal is not None:
            legal_nums = [str(i) for i, c in enumerate(cards, 1) if c in legal]
            print(f"\n{label}: " + "  ".join(parts) + f"   (legal: {', '.join(legal_nums)})")
        else:
            print(f"\n{label}: " + "  ".join(parts))

    def show_trick(
        self,
        trick: list[tuple[int, Card]],
        trump: Suit,
        player_names: list[str],
    ) -> None:
        if not trick:
            print("\n  (You lead this trick)")
            return
        print("\n  Trick so far:")
        for seat, card in trick:
            print(f"    {player_names[seat]:8s}: {self._card_str(card, is_trump=card.is_trump(trump))}")

    def show_scores(
        self,
        game_scores: list[int],
        trick_scores: list[int],
        team_names: list[str],
    ) -> None:
        print(f"\n  Hand tricks — {team_names[0]}: {trick_scores[0]}  |  {team_names[1]}: {trick_scores[1]}")
        print(f"  Game score  — {team_names[0]}: {game_scores[0]}  |  {team_names[1]}: {game_scores[1]}")

    # ------------------------------------------------------------------
    # Input helpers
    # ------------------------------------------------------------------

    def _input(self, prompt: str) -> str:
        try:
            return input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            raise SystemExit(0)

    def prompt_bid_round1(
        self,
        upcard: Card,
        is_dealer: bool,
        hand: list[Card],
    ) -> tuple[str, bool]:
        dealer_note = " (you are the dealer and would pick it up)" if is_dealer else ""
        print(f"\nRound 1: Order up {self._card_str(upcard)}{dealer_note}?")
        while True:
            raw = self._input("  (o)rder up  (p)ass  > ").lower()
            if raw in ("o", "order", "order up"):
                alone = self._ask_alone()
                return "order", alone
            if raw in ("p", "pass"):
                return "pass", False
            print("  Please enter 'o' to order up or 'p' to pass.")

    def prompt_bid_round2(
        self,
        excluded_suit: Suit,
        is_dealer: bool,
        hand: list[Card],
    ) -> tuple[str, bool]:
        options = [s for s in Suit if s != excluded_suit]
        opt_str = "  ".join(
            f"({s.value.lower()}){s.name.lower()[1:]}" for s in options
        )
        dealer_note = "  [You must call — stick the dealer]" if is_dealer else ""
        print(f"\nRound 2: Name a suit (not {excluded_suit.name}){dealer_note}")
        print(f"  Options: {opt_str}  (p)ass")
        valid = {s.value.lower(): s.value for s in options}
        valid.update({s.name.lower(): s.value for s in options})
        while True:
            raw = self._input("  > ").lower().strip()
            if raw in ("p", "pass") and not is_dealer:
                return "pass", False
            if raw in valid:
                alone = self._ask_alone()
                return valid[raw], alone
            print(f"  Please enter a suit name or letter, or 'p' to pass.")

    def _ask_alone(self) -> bool:
        raw = self._input("  Go alone? (y/n) > ").lower()
        return raw in ("y", "yes")

    def prompt_card(self, hand: list[Card], legal: list[Card]) -> Card:
        legal_indices = [i + 1 for i, c in enumerate(hand) if c in legal]
        while True:
            raw = self._input(f"  Play a card {legal_indices}: ").strip()
            try:
                idx = int(raw) - 1
                if 0 <= idx < len(hand) and hand[idx] in legal:
                    return hand[idx]
            except ValueError:
                pass
            print(f"  Choose a number from {legal_indices}.")

    def prompt_discard(self, hand: list[Card], trump: Suit) -> Card:
        print("\nYou picked up the upcard. Choose a card to discard:")
        self.show_hand(hand, trump=trump)
        while True:
            raw = self._input(f"  Discard (1-{len(hand)}): ").strip()
            try:
                idx = int(raw) - 1
                if 0 <= idx < len(hand):
                    return hand[idx]
            except ValueError:
                pass
            print(f"  Enter a number between 1 and {len(hand)}.")

    def prompt_view_grade(self) -> bool:
        raw = self._input("\nView hand grade report? (y/n) > ").lower()
        return raw in ("y", "yes")

    def wait_for_enter(self, message: str = "") -> None:
        self._input(message)

    # ------------------------------------------------------------------
    # Grade report display
    # ------------------------------------------------------------------

    def show_grade_report(self, report: "GradeReport") -> None:  # noqa: F821
        print("\n" + "=" * 60)
        print("                  HAND GRADE REPORT")
        print("=" * 60)

        print("\nBIDDING:")
        if not report.bid_grades:
            print("  (No bidding decisions recorded for you this hand)")
        for i, g in enumerate(report.bid_grades, 1):
            d = g.decision
            action_str = g.decision.human_choice
            if action_str not in ("order", "pass"):
                action_str = f"called {Suit(action_str).name}"
            alone_str = " + alone" if d.human_alone else ""
            verdict_color = VERDICT_COLOR.get(g.verdict, "") if self._color else ""
            reset = Style.RESET_ALL if self._color else ""
            print(f"\n  [{i}] Round {d.round} — You: {action_str}{alone_str}  "
                  f"[{verdict_color}{g.verdict}{reset}]")
            ai_action = g.ai_action
            if ai_action not in ("order", "pass"):
                ai_action = f"call {Suit(ai_action).name}"
            ai_alone_str = " + alone" if g.ai_alone else ""
            print(f"      AI recommended: {ai_action}{ai_alone_str}")
            print(f"      {g.explanation}")

        print("\nCARD PLAY:")
        if not report.play_grades:
            print("  (No card plays recorded)")
        for i, g in enumerate(report.play_grades, 1):
            p = g.play
            verdict_color = VERDICT_COLOR.get(g.verdict, "") if self._color else ""
            reset = Style.RESET_ALL if self._color else ""
            print(f"\n  [{i}] Trick {p.trick_num + 1} — You played: "
                  f"{self._card_str(p.human_card)}  [{verdict_color}{g.verdict}{reset}]")
            if g.verdict != "OPTIMAL":
                print(f"      AI recommended: {self._card_str(g.ai_card)}")
            print(f"      {g.explanation}")

        print("\n" + "-" * 60)
        print(f"  {report.summary}")
        print("=" * 60)
