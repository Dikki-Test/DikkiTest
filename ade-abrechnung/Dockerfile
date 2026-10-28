FROM node:22-alpine

WORKDIR /app
COPY index.html server.js ./
RUN mkdir /data && chown node:node /data

ENV PORT=8080 DATA_FILE=/data/ade.json
USER node
EXPOSE 8080
VOLUME /data
HEALTHCHECK --interval=30s --timeout=3s CMD wget -qO- http://127.0.0.1:8080/healthz || exit 1

CMD ["node", "server.js"]
