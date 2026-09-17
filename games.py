from __future__ import annotations
import hashlib, random, secrets


def provably_fair(client_seed: str):
    server = secrets.token_hex(32)
    digest = hashlib.sha256(server.encode()).hexdigest()
    rng = random.Random(f"{server}:{client_seed}")
    return server, digest, rng

def parse_amount(raw: str) -> float:
    value = raw.lower().replace("$", "").replace(",", "").strip()
    points = float(value)
    if points <= 0 or points > 1_000_000: raise ValueError("Enter a valid positive point amount.")
    return round(points, 4)

def card_value(card: str) -> int:
    rank = card[:-1]
    return 11 if rank == "A" else 10 if rank in "JQK" else int(rank)

def hand_total(cards):
    total, aces = sum(card_value(c) for c in cards), sum(c[:-1] == "A" for c in cards)
    while total > 21 and aces: total -= 10; aces -= 1
    return total

def deck(rng):
    cards = [f"{rank}{suit}" for rank in ["A", *map(str, range(2,11)), "J", "Q", "K"] for suit in "♣♦♥♠"]
    rng.shuffle(cards); return cards
