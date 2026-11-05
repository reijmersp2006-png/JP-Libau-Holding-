"""JP-libau Holding: all-in-one trading- en onderzoeksbot.

Opbouw:
- ``jplh.data``     koersen ophalen (Bitvavo, Yahoo, ECB, DexScreener-radar, demo)
- ``jplh.store``    SQLite-opslag met het tijdstip van ophalen (geen kijken in de toekomst)
- ``jplh.risk``     risico-afdeling met vetorecht en vaste grenzen
- ``jplh.ledger``   boekhouding in euro
- ``jplh.broker``   paper-broker met realistische kosten
- ``jplh.journal``  logboek: elke beslissing met reden
"""

__version__ = "0.1.0"
