"""Regression coverage for the canonical TD3C route name in the XLSX feed."""

import os
import sys

import pandas as pd

sys.path.insert(0, os.getcwd())
from utils import read_xlsx_file


def test_xlsx_parser_normalizes_td3c():
    routes = pd.Series(['TD3', 'td3c', 'TD7'])
    got = read_xlsx_file._normalize_route_names(routes)

    assert got.tolist() == ['TD3C', 'TD3C', 'TD7']


if __name__ == '__main__':
    test_xlsx_parser_normalizes_td3c()
    print('test_xlsx_parser_normalizes_td3c OK')
