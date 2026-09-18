"""Слой шардирования (лабораторные №5 и №6).

* `router.py`  — стратегии выбора шарда: hash % N и Consistent Hashing;
* `pools.py`   — по пулу соединений на каждый PostgreSQL-шард;
* `queries.py` — single-shard запросы и scatter-gather поверх всех шардов.
"""
