from src.agent import run


class Ctx:
    pass


def test_run():
    assert run(Ctx(), {})["ok"] is True
