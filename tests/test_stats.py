from subsentry.core.stats import median, mad

def test_median():
    assert median([1,2,3]) == 2.0

def test_mad_zero():
    assert mad([5,5,5]) == 0.0
