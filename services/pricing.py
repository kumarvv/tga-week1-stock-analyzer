from datetime import datetime, timezone
from typing import Protocol
from models import Quote, D

class PriceProvider(Protocol):
    def quotes(self, symbols: list[str]) -> dict[str, Quote]: ...

class ManualProvider:
    def __init__(self, quotes):
        self.values = quotes
    def quotes(self, symbols):
        return {s: self.values[s] for s in symbols if s in self.values}

class DemoProvider:
    def quotes(self, symbols):
        return {s: Quote(D({'AAPL': '215', 'MSFT': '450'}.get(s, '100')), datetime(2025, 4, 15, 20, tzinfo=timezone.utc), 'Synthetic demo', True) for s in symbols}
