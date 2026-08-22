from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ProviderMeta:
    provider_id: str
    name: str
    category: str
    description: str = ''
    max_chunk_chars: int = 5000
    max_chunks_per_sec: float = 1.0
    requires_auth: bool = False
    required_keys: list[str] = field(default_factory=list)
    supported_formats: list[str] = field(default_factory=list)


class BaseProvider(ABC):
    meta: ProviderMeta

    def __init__(self):
        from src.core.config import config
        self.config = config

    @abstractmethod
    def validate_auth(self) -> tuple[bool, str]:
        ...

    def get_limits(self) -> dict:
        return {
            'max_chunk_chars': self.meta.max_chunk_chars,
            'max_chunks_per_sec': self.meta.max_chunks_per_sec,
        }


class TranslationProvider(BaseProvider):
    def process(self, text: str, target_lang: str = 'zh-Hans',
                source_lang: str = 'en') -> str:
        return self._translate(text, target_lang, source_lang)

    @abstractmethod
    def _translate(self, text: str, target_lang: str,
                   source_lang: str = 'en') -> str:
        ...


class TranscriptionProvider(BaseProvider):
    ...


class ParseProvider(BaseProvider):
    @abstractmethod
    def process_file(self, input_path: str, output_dir: str) -> str:
        ...


class ProviderRegistry:
    _providers: dict[str, type[BaseProvider]] = {}

    @classmethod
    def register(cls, provider_cls: type[BaseProvider]):
        inst = provider_cls()
        cls._providers[inst.meta.provider_id] = provider_cls
        return provider_cls

    @classmethod
    def list_all(cls) -> list[ProviderMeta]:
        return [p.meta for p in cls._providers.values()]

    @classmethod
    def list_by_category(cls, category: str) -> list[ProviderMeta]:
        return [p.meta for p in cls._providers.values()
                if p.meta.category == category]

    @classmethod
    def get(cls, provider_id: str) -> Optional[BaseProvider]:
        provider_cls = cls._providers.get(provider_id)
        if provider_cls:
            return provider_cls()
        return None

    @classmethod
    def get_meta(cls, provider_id: str) -> Optional[ProviderMeta]:
        provider_cls = cls._providers.get(provider_id)
        if provider_cls:
            return provider_cls.meta
        return None

    @classmethod
    def default_for(cls, category: str) -> Optional[str]:
        from src.core.config import config
        key = f'DEFAULT_PROVIDER_{category.upper()}'
        return config.get(key) or None


registry = ProviderRegistry()
