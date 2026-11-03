"""Serializers of the email channel's public routes."""

from rest_framework import serializers


class ConversationMessageSerializer(serializers.Serializer):
    """A message written on the conversation page."""

    body = serializers.CharField(max_length=10000)


class ConversationAttachmentSerializer(serializers.Serializer):
    """A file sent from the conversation page, with an optional message.

    The file itself is checked by ``TicketAttachmentSerializer``, as the widget's.
    """

    file = serializers.FileField()
    body = serializers.CharField(
        max_length=10000, required=False, allow_blank=True, default=""
    )
