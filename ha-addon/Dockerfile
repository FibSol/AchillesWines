ARG BUILD_FROM
FROM $BUILD_FROM AS base

# Install docker + compose so we can launch our own stack
RUN apk add --no-cache docker-cli docker-compose bash curl sqlite

COPY run.sh /
RUN chmod +x /run.sh

CMD ["/run.sh"]
