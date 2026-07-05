# Cogit read-only web viewer (COG-038/051). Zero dependencies by design:
# the image is stock Python plus the prototype tree, nothing to install.
FROM python:3.13-alpine

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY prototype /app/prototype

EXPOSE 8323
# --host 0.0.0.0 is container-internal; publish the port to 127.0.0.1 on
# the host (see docker-compose.yml) — the viewer has no auth by design.
CMD ["python3", "/app/prototype/integrations/web_viewer.py", \
     "--repo", "/journal", "--host", "0.0.0.0", "--port", "8323"]
