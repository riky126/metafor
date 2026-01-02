from metafor.core import create_signal

count, set_count = create_signal(0)


def count_up(value):
    set_count(count() + value)
    
    return count()

def count_down(value):
    set_count(count()-value)
    return count()


def test_count():
    assert count_up(1) == 1