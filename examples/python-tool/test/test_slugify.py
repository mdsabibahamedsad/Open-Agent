from src.slugify import slugify


class Ctx:
    pass


def test_slugify():
    assert slugify(Ctx(), {"title": "Hello, World!"}) == {"slug": "hello-world"}


def test_empty():
    assert slugify(Ctx(), {"title": "!!!"}) == {"slug": "untitled"}
