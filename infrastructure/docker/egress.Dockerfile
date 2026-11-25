FROM python:3.13-slim-bookworm
WORKDIR /srv
COPY infrastructure/egress/proxy.py ./
USER 65534:65534
EXPOSE 3128
CMD ["python", "-B", "/srv/proxy.py"]
