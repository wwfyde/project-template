from .models import Item, User
from .schema import MemoryTable


class AppRepository:
    def __init__(self) -> None:
        self.user = MemoryTable[User]("user")
        self.item = MemoryTable[Item]("item")
