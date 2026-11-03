from pydantic import BaseModel


class User(BaseModel):
    id: int
    username: str
    age: int


class Item(BaseModel):
    id: int
    name: str
    price: float
