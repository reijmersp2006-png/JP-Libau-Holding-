"""NEXUS AI: de controlelaag en API boven op de JP-libau Holding.

De holding (``jplh``) doet het echte werk: koersen ophalen, paper trading, risico, backtests.
NEXUS leest die stand, labelt elke waarde naar herkomst (LIVE, DELAYED, HISTORICAL,
SIMULATED, UNAVAILABLE) en voegt de besturing toe die boven alle bots hoort: handelsmodus,
noodstop, Risk Guardian voor voorstellen en een audit-trail. Live handelen bestaat niet in
deze versie en kan ook niet aangezet worden.
"""

__version__ = "0.1.0"
