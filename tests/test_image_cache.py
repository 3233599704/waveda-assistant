from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from raggg.desktop.image_cache import ImageDataUriCache


class ImageDataUriCacheTests(unittest.TestCase):
    def test_refreshes_when_file_changes(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "image.png"
            path.write_bytes(b"first")
            cache = ImageDataUriCache()
            first = cache.get(path)

            path.write_bytes(b"second-version")
            second = cache.get(path)

            self.assertTrue(first.startswith("data:image/png;base64,"))
            self.assertNotEqual(first, second)

    def test_evicts_old_entries_when_capacity_is_reached(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            first_path = root / "first.png"
            second_path = root / "second.png"
            first_path.write_bytes(b"first")
            second_path.write_bytes(b"second")
            cache = ImageDataUriCache(max_entries=1)

            cache.get(first_path)
            cache.get(second_path)

            self.assertEqual(len(cache._entries), 1)


if __name__ == "__main__":
    unittest.main()
