import pytest
from media_organizer import 标题前缀, 解析日期, 解析文件名

def test_标题前缀_examples():
    assert 标题前缀('蓝色体操服 (20).jpg') == '蓝色体操服'
    assert 标题前缀('王艺纯16.mp4') == '王艺纯'
    assert 标题前缀('12.jpg') is None

def test_解析日期_examples():
    assert 解析日期('2025-06-01') is not None
    assert 解析日期('not a date') is None

def test_解析文件名_basic():
    cfg = {'文件名规则': [['微信图片', '微信图片'], ['IMG-', '相机']], '文件名正则规则': []}
    src, dt = 解析文件名('IMG-20250601-123.jpg', cfg)
    assert src and src[0] == '相机'
