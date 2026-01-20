"""
Auction-Context Module – limit-chaser & auction-theory logic
"""
import math
import logging

log = logging.getLogger('auction')

def limit_chase(book, side, size, max_slip=0.02):
    """Walk the book until size filled without exceeding max_slip.

    Returns dict {'price': float, 'qty': float, 'slip_pct': float} or None if cannot fill.
    """
    lvl = 0
    rem = size
    ttl_qty = 0
    wavg = 0

    # choose levels depending on side: if selling, we walk bids, else asks
    levels = book.get('bids') if side == 'sell' else book.get('asks')
    if not levels:
        return None

    try:
        ref = float(levels[0][0])
    except (IndexError, ValueError):
        return None

    while rem > 0 and lvl < len(levels):
        try:
            px = float(levels[lvl][0])
            avail = float(levels[lvl][1])
        except (IndexError, ValueError):
            break
        slip = abs(px - ref) / ref if ref else 0
        if slip > max_slip:
            break
        take = min(rem, avail)
        wavg += take * px
        ttl_qty += take
        rem -= take
        lvl += 1

    if ttl_qty == 0:
        return None

    avg_price = wavg / ttl_qty
    return {'price': avg_price, 'qty': ttl_qty, 'slip_pct': abs(avg_price - ref) / ref if ref else 0.0}


def auction_micro_timing(book, side):
    """Return 0-1 score: 1 = perfect auction edge (thin book, wide spread)."""
    try:
        b = float(book['bids'][0][0])
        a = float(book['asks'][0][0])
    except (IndexError, ValueError):
        return 0.0
    spread = (a - b) / b if b else 0.0
    bid_depth = sum([float(x[1]) for x in book.get('bids', [])[:5]])
    ask_depth = sum([float(x[1]) for x in book.get('asks', [])[:5]])
    depth = min(bid_depth, ask_depth)
    return min(1.0, spread * 100 + 1.0 / (depth + 1.0))
