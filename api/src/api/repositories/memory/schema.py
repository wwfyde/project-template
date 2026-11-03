from typing import Any, Callable, Generic, TypeVar

T = TypeVar("T")


class MemoryTable(Generic[T]):
    def __init__(self, name: str) -> None:
        self.name = name
        self._rows: list[T] = []

    def insert(self, obj: T) -> None:
        self._rows.append(obj)

    def delete(self, predicate: Callable[[T], bool]) -> int:
        before_count = len(self._rows)
        self._rows = [row for row in self._rows if not predicate(row)]
        return before_count - len(self._rows)

    def list_all(self) -> list[T]:
        return list(self._rows)

    def list_sorted(
        self,
        key: Callable[[T], Any],
        descending: bool = False,
    ) -> list[T]:
        return sorted(self._rows, key=key, reverse=descending)

    def sort_in_place(
        self,
        key: Callable[[T], Any],
        descending: bool = False,
    ) -> None:
        self._rows.sort(key=key, reverse=descending)
