"""Chat channels module with plugin architecture."""

from hazel.channels.base import BaseChannel
from hazel.channels.manager import ChannelManager

__all__ = ["BaseChannel", "ChannelManager"]
