"""Keep proprietary-corpus evaluation explicit in the public source edition."""
from pathlib import Path
import pytest


def pytest_addoption(parser):
    parser.addoption('--with-proprietary-corpus', action='store_true', default=False,
                     help='Run integration evaluations requiring separately authorized original documents/index.')


def pytest_collection_modifyitems(config, items):
    if config.getoption('--with-proprietary-corpus'):
        return
    names = {'test_c4_retrieval.py', 'test_english_retrieval_live.py'}
    reason = 'Original enterprise corpus/index is not distributed in this public edition.'
    for item in items:
        if Path(str(item.fspath)).name in names:
            item.add_marker(pytest.mark.skip(reason=reason))
