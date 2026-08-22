from .base import ProviderRegistry, BaseProvider, TranslationProvider, TranscriptionProvider, ParseProvider, ProviderMeta

from . import translate
from . import transcribe
from . import parse

registry = ProviderRegistry

