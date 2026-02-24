FROM node:22-slim

WORKDIR /app

RUN npm install -g openclaw@latest

COPY workspace/ /app/workspace/
COPY config.yaml /app/config.yaml

EXPOSE 3100

CMD ["openclaw", "start", "--config", "/app/config.yaml"]
