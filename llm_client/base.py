from abc import ABC, abstractmethod


class Generator(ABC):
    """Provider-agnostic text generation interface."""

    @abstractmethod
    def generate(self, context: str, question: str) -> str:
        """Generate an answer grounded in the supplied job context."""
