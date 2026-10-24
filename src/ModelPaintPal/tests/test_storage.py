# -*- coding: utf-8 -*-
"""存储层健壮性测试（R18：集合写入拒绝非字典项；损坏文件可恢复）。"""

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.core import paths  # noqa: E402
from app.core.storage import CollectionStore, JsonStore  # noqa: E402


class TestCollectionStore(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._orig = paths.USER_DATA_DIR
        paths.USER_DATA_DIR = self.tmp

    def tearDown(self):
        paths.USER_DATA_DIR = self._orig

    def test_append_and_load_roundtrip(self):
        store = CollectionStore("c.json", limit=10)
        store.append({"uid": "1", "hex": "#ffffff"})
        self.assertEqual(len(store.load()), 1)

    def test_append_rejects_non_dict(self):
        store = CollectionStore("c.json", limit=10)
        store.append({"uid": "1", "hex": "#ffffff"})
        # 非字典项应被拒绝，且已有数据不丢
        result = store.append("not-a-dict")
        items = store.load()
        self.assertNotIn("not-a-dict", items)
        self.assertEqual(len(items), 1)
        self.assertEqual(len(result), 1)

    def test_load_filters_non_dict_from_disk(self):
        # 磁盘上若已混入非字典项，load 应过滤掉，避免上层解析崩溃
        store = CollectionStore("c.json", limit=10)
        store.save([{"uid": "1"}, "junk", 123, None])
        items = store.load()
        self.assertEqual(items, [{"uid": "1"}])

    def test_dedup_by_key(self):
        store = CollectionStore("c.json", limit=10)
        store.append({"uid": "1", "hex": "#111111"})
        store.append({"uid": "2", "hex": "#111111"}, dedup_key="hex")
        # 同 hex 去重置顶，总数不变
        self.assertEqual(len(store.load()), 1)
        self.assertEqual(store.load()[0]["uid"], "2")

    def test_evicts_beyond_limit(self):
        """超过上限时裁掉最旧的，保留最新的在最前（R43）。"""
        store = CollectionStore("c.json", limit=3)
        for i in range(5):
            store.append({"uid": str(i)})
        items = store.load()
        self.assertEqual(len(items), 3)
        self.assertEqual([it["uid"] for it in items], ["4", "3", "2"])

    def test_dedup_then_evict(self):
        store = CollectionStore("c.json", limit=2)
        store.append({"uid": "a", "hex": "#000000"})
        store.append({"uid": "b", "hex": "#111111"})
        store.append({"uid": "c", "hex": "#000000"}, dedup_key="hex")  # 与 a 同 hex
        self.assertEqual([it["uid"] for it in store.load()], ["c", "b"])

    def test_remove_specific(self):
        store = CollectionStore("c.json", limit=10)
        store.append({"uid": "a"})
        store.append({"uid": "b"})
        store.remove(lambda it: it.get("uid") == "a")
        self.assertEqual([it["uid"] for it in store.load()], ["b"])

    def test_clear(self):
        store = CollectionStore("c.json", limit=10)
        store.append({"uid": "a"})
        self.assertEqual(store.clear(), [])
        self.assertEqual(store.load(), [])

    def test_empty_collection_loads_empty_list(self):
        store = CollectionStore("e.json", limit=10)
        self.assertEqual(store.load(), [])

    def test_exists_and_delete(self):
        store = JsonStore("d.json", lambda: {})
        self.assertFalse(store.exists())
        store.save({"a": 1})
        self.assertTrue(store.exists())
        self.assertTrue(store.delete())
        self.assertFalse(store.exists())


class TestJsonStoreRecovery(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._orig = paths.USER_DATA_DIR
        paths.USER_DATA_DIR = self.tmp

    def tearDown(self):
        paths.USER_DATA_DIR = self._orig

    def test_corrupt_file_returns_default_and_quarantines(self):
        store = JsonStore("data.json", lambda: {"ok": True})
        # 写入一段损坏内容
        store.path.write_text("{ this is not json ", encoding="utf-8")
        data = store.load()
        self.assertEqual(data, {"ok": True})
        # 损坏文件被隔离为 .corrupt
        self.assertTrue(list(self.tmp.glob("data.json.corrupt*")))

    def test_save_non_serializable_returns_false(self):
        store = JsonStore("x.json", lambda: {})
        # set 不可 JSON 序列化：应捕获异常返回 False，而不是抛出
        self.assertFalse(store.save({"bad": {1, 2, 3}}))

    def test_atomic_write_no_partial_file(self):
        store = JsonStore("data.json", lambda: {})
        store.save({"a": 1})
        self.assertTrue(store.path.exists())
        # 重新读取应完整
        self.assertEqual(store.load(), {"a": 1})


if __name__ == "__main__":
    unittest.main()
