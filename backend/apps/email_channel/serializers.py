"""Serializers of the email channel's public routes."""

from rest_framework import serializers

from apps.tickets.models import TicketMessage
from apps.tickets.serializers import WidgetMessageSerializer


class ConversationReplySerializer(serializers.Serializer):
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


class ConversationMessageSerializer(WidgetMessageSerializer):
    """A message as the conversation page shows it.

    No name on the requester's side: the ticket's session, or a mail's sender, may
    be someone other than the person the link was mailed to.
    """

    sender_name = serializers.SerializerMethodField()

    def get_sender_name(self, message: TicketMessage) -> str:
        if message.sender_type == TicketMessage.SenderType.USER:
            return ""
        return message.sender_name
