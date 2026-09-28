import csv
import io

from rest_framework.renderers import BaseRenderer


class CSVRenderer(BaseRenderer):
    """Renders a flat dict as a two-column CSV. Selected by ?format=csv or Accept: text/csv."""

    media_type = "text/csv"
    format = "csv"
    charset = "utf-8"

    def render(self, data, accepted_media_type=None, renderer_context=None):
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["field", "value"])
        for key, value in (data or {}).items():
            writer.writerow([key, value])
        return buffer.getvalue()
