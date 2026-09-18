"""Router: по shard key определяет, на каком PostgreSQL лежит запись.

Две стратегии, обе с одинаковым интерфейсом `route(key) -> shard_id`:

* `ModuloRouter`         — hash(key) % N, простейший вариант;
* `ConsistentHashRouter` — hash ring с виртуальными узлами.

Хеш берём из hashlib, а не встроенный `hash()`: тот для строк солится
случайным значением при каждом старте процесса (PYTHONHASHSEED), поэтому
одна и та же запись после рестарта уехала бы на другой шард.
"""

from __future__ import annotations

import bisect
import hashlib
from typing import Dict, List, Sequence

# Размер кольца: хеш укладываем в 64 бита.
RING_SIZE = 2 ** 64


def hash_key(key: object) -> int:
    """Стабильный 64-битный хеш ключа.

    blake2b выбран потому, что он быстрый и есть в стандартной библиотеке;
    криптостойкость здесь не нужна, нужна равномерность и воспроизводимость.
    """
    digest = hashlib.blake2b(str(key).encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big")


class ShardRouter:
    """Общий интерфейс. Backend работает только с ним и не знает стратегию."""

    name = "base"

    def __init__(self, shard_ids: Sequence[int]) -> None:
        if not shard_ids:
            raise ValueError("список шардов пуст")
        self.shard_ids: List[int] = list(shard_ids)

    def route(self, key: object) -> int:
        raise NotImplementedError

    def __repr__(self) -> str:  # pragma: no cover - для логов
        return f"<{type(self).__name__} shards={self.shard_ids}>"


class ModuloRouter(ShardRouter):
    """shard = hash(key) % N.

    Плюс: считается за микросекунды, распределяет практически идеально ровно.
    Минус: N входит в саму формулу, поэтому смена числа шардов меняет адрес
    почти каждой записи (см. задание 5 лабораторной).
    """

    name = "modulo"

    def route(self, key: object) -> int:
        return self.shard_ids[hash_key(key) % len(self.shard_ids)]


class ConsistentHashRouter(ShardRouter):
    """Consistent Hashing: кольцо хешей + виртуальные узлы.

    Каждый шард представлен на кольце не одной точкой, а `virtual_nodes`
    точками (`shard-0#0`, `shard-0#1`, ...). Ключ кладётся в первую точку
    по часовой стрелке от hash(key).

    Зачем виртуальные узлы: с одной точкой на шард три случайные точки
    делят кольцо на очень неравные дуги, и шарды получают заметно разные
    доли данных. Сотня точек на шард усредняет дуги и выравнивает нагрузку.

    Главное свойство: число шардов не входит в формулу адреса. При
    добавлении шарда переезжают только ключи, попавшие на его новые дуги,
    то есть примерно 1/(N+1) данных, а не почти всё.
    """

    name = "consistent"

    def __init__(self, shard_ids: Sequence[int], virtual_nodes: int = 150) -> None:
        super().__init__(shard_ids)
        self.virtual_nodes = virtual_nodes
        # Отсортированный список точек кольца + позиция -> shard_id.
        self._ring: List[int] = []
        self._owner: Dict[int, int] = {}
        for shard_id in self.shard_ids:
            for vnode in range(virtual_nodes):
                point = hash_key(f"shard-{shard_id}#{vnode}")
                # Коллизия точек на 64 битах практически невозможна,
                # но если случится — просто пропускаем дубль.
                if point not in self._owner:
                    self._owner[point] = shard_id
                    self._ring.append(point)
        self._ring.sort()

    def route(self, key: object) -> int:
        point = hash_key(key)
        # Первая точка кольца, которая >= хеша ключа.
        idx = bisect.bisect_right(self._ring, point)
        if idx == len(self._ring):
            idx = 0  # кольцо замкнуто: после последней точки идёт первая
        return self._owner[self._ring[idx]]


def build_router(strategy: str, shard_ids: Sequence[int], virtual_nodes: int = 150) -> ShardRouter:
    """Фабрика: строит router по названию стратегии из конфигурации."""
    if strategy == "modulo":
        return ModuloRouter(shard_ids)
    if strategy == "consistent":
        return ConsistentHashRouter(shard_ids, virtual_nodes=virtual_nodes)
    raise ValueError(f"неизвестная стратегия шардирования: {strategy!r}")
