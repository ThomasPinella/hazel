"""Message bus module for decoupled channel-agent communication."""

from hazel.bus.events import InboundMessage, OutboundMessage
from hazel.bus.queue import MessageBus

__all__ = ["MessageBus", "InboundMessage", "OutboundMessage"]
