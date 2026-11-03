from api.repositories.memory.models import Item
from api.repositories.memory.repository import AppRepository

if __name__ == "__main__":
    repo = AppRepository()

    # 插入
    repo.item.insert(Item(id=1, name="Keyboard", price=299.0))
    repo.item.insert(Item(id=2, name="Mouse", price=129.0))
    repo.item.insert(Item(id=3, name="Monitor", price=1599.0))

    # 根据对象的 price 属性降序获取
    expensive_first = repo.item.list_sorted(key=lambda x: x.price, descending=True)

    # 根据属性条件删除
    repo.item.delete(lambda x: x.id == 2)
    print(repo.item.list_all())
    print(repo.user.list_all())
