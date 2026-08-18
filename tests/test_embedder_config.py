from __future__ import annotations

import os
import sys
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from core.retrieval import embedder


class EmbedderConfigTests(unittest.TestCase):
    def tearDown(self) -> None:
        embedder._default = None

    def test_default_provider_is_disabled(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            embedder._default = None

            selected = embedder.get_default_embedder()

        self.assertFalse(selected.available)
        self.assertEqual(selected.dim, 0)
        self.assertEqual(selected.embed(["hello"]), [[]])

    def test_openai_provider_requires_api_key(self) -> None:
        with patch.dict(os.environ, {"KDG_EMBED_PROVIDER": "openai"}, clear=True):
            embedder._default = None

            selected = embedder.get_default_embedder()

        self.assertFalse(selected.available)
        self.assertEqual(selected.dim, 0)

    def test_openai_provider_uses_compatible_embeddings_client(self) -> None:
        fake_openai = ModuleType("openai")

        class FakeEmbeddings:
            def create(self, **kwargs):
                self.kwargs = kwargs
                return SimpleNamespace(
                    data=[
                        SimpleNamespace(index=1, embedding=[0.3, 0.4]),
                        SimpleNamespace(index=0, embedding=[0.1, 0.2]),
                    ]
                )

        class FakeOpenAI:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
                self.embeddings = FakeEmbeddings()

        fake_openai.OpenAI = FakeOpenAI

        env = {
            "KDG_EMBED_PROVIDER": "openai",
            "KDG_EMBED_API_KEY": "test-key",
            "KDG_EMBED_MODEL": "embedding-model",
            "KDG_EMBED_DIM": "2",
        }
        with (
            patch.dict(os.environ, env, clear=True),
            patch.dict(sys.modules, {"openai": fake_openai}),
        ):
            embedder._default = None

            selected = embedder.get_default_embedder()

            self.assertTrue(selected.available)
            self.assertEqual(selected.dim, 2)
            self.assertEqual(selected.embed(["a", "b"]), [[0.1, 0.2], [0.3, 0.4]])


if __name__ == "__main__":
    unittest.main()
