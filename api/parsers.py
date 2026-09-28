import json
from decimal import Decimal

from django.conf import settings
from rest_framework.exceptions import ParseError
from rest_framework.parsers import JSONParser


class DecimalJSONParser(JSONParser):
    """JSON parser that turns every JSON number with a fraction into Decimal, never float."""

    def parse(self, stream, media_type=None, parser_context=None):
        encoding = (parser_context or {}).get("encoding", settings.DEFAULT_CHARSET)
        try:
            return json.loads(stream.read().decode(encoding), parse_float=Decimal)
        except ValueError as exc:
            raise ParseError(f"JSON parse error - {exc}") from exc
