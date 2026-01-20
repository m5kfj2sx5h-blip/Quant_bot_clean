"""
# responsible for all conversions from one form of money to another outside triangular arbitrage.
# an on demand triangular arbitrage machine with specified pairs and finds the cheapest AND fastest routes for the [MONEY MANAGER].
# tries to keep the drift across accounts below 15% by intra-exchange triangular conversions, so [[Q-bot]] runs smoothly.
# Does not interrupt arbitrage system
# One job: Reduces the amount needed to transfer by prioritizing triangular conversions (intra-exchange) over any cross-account transfers whenever possible to eliminate transfer fees entirely.

# originally triangular.py # needs to be redone from scratch 
Triangular arbitrage detector
"""
import json
import itertools
import logging

log = logging.getLogger('tri')

PAIRS = ['BTC-USD','ETH-USD','SOL-USD','ETH-BTC','SOL-BTC','SOL-ETH']
PATHS = list(itertools.permutations(['USD','BTC','ETH','SOL'], 3))

def detect_triangle(books, min_prof=0.08):
    """
    books dict  {'exchange': {'BTC-USD':{bids:[],asks:[]}, ...}
    returns [{'path':USD→BTC→ETH→USD, 'ex':kraken, 'prof_pct':0.11}, ...]
    """
    out = []
    for ex in books:
    for p in PATHS:
    try:
    a = float(books[ex][f'{p[1]}-{p[0]}']['asks'][0][0])   # USD→BTC
    b = float(books[ex][f'{p[2]}-{p[1]}']['asks'][0][0])   # BTC→ETH
    c = float(books[ex][f'{p[0]}-{p[2]}']['bids'][0][0])   # ETH→USD
    prof = (1/a * 1/b * c - 1) * 100
    if prof > min_prof:
        out.append({'ex':ex, 'path':p, 'prof_pct':prof})
    except: continue
return sorted(out, key=lambda x: x['prof_pct'], reverse=True)