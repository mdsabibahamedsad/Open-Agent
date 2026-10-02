from src.tool import greet


class Ctx:
    pass


def test_greet():
    assert greet(Ctx(), {"name": "Ada"}) == {"greeting": "Hello, Ada!"}
