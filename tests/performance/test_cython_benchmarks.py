"""Cython benchmarks — verifies compilation works and modules load."""
import time

N = 100_000


def test_cython_lrucache():
    from AssetsManager.core.cache import LRUCache
    cache = LRUCache(1000)
    start = time.perf_counter()
    for i in range(N):
        cache.set(f'k{i}', f'v{i}')
    set_ops = N / (time.perf_counter() - start)
    start = time.perf_counter()
    for i in range(N):
        cache.get(f'k{i}')
    get_ops = N / (time.perf_counter() - start)
    print(f'\nLRUCache: set={set_ops:,.0f} get={get_ops:,.0f} ops/s')
    assert set_ops > 0


def test_cython_color_utils():
    from AssetsManager.core.color_utils import _hex_to_rgb, _rgb_to_hex
    start = time.perf_counter()
    for i in range(N):
        _hex_to_rgb('#FF0000')
    h2r = N / (time.perf_counter() - start)
    start = time.perf_counter()
    for i in range(N):
        _rgb_to_hex(255, 0, 0)
    r2h = N / (time.perf_counter() - start)
    print(f'\ncolor_utils: hex_to_rgb={h2r:,.0f} rgb_to_hex={r2h:,.0f} ops/s')
    assert h2r > 0


def test_cython_format_size():
    from AssetsManager.core.format_utils import format_size
    start = time.perf_counter()
    for i in range(N):
        format_size(i * 1024)
    ops = N / (time.perf_counter() - start)
    print(f'\nformat_size: {ops:,.0f} ops/s')
    assert ops > 0


def test_cython_asset_filters():
    from AssetsManager.application.asset_filters import matches_search, is_hidden
    start = time.perf_counter()
    for i in range(N):
        matches_search('test_file.txt', 'test')
    ms = N / (time.perf_counter() - start)
    start = time.perf_counter()
    for i in range(N):
        is_hidden('.hidden')
    ih = N / (time.perf_counter() - start)
    print(f'\nasset_filters: matches_search={ms:,.0f} is_hidden={ih:,.0f} ops/s')
    assert ms > 0
