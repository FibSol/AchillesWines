FROM node:22-alpine

# Build tools required for better-sqlite3 native module
RUN apk add --no-cache python3 py3-pip make g++ git

WORKDIR /app

# Clone the Achilles Wines repository at build time
# CACHEBUST forces a fresh clone when the version changes
ARG CACHEBUST=1.0.2
ARG REPO=https://github.com/FibSol/AchillesWines.git
ARG BRANCH=main
RUN echo "cachebust=${CACHEBUST}" && git clone --depth=1 --branch ${BRANCH} ${REPO} .

# Install Node dependencies and build Next.js (standalone output)
RUN npm install && \
    npm run build && \
    cp -r public .next/standalone/public && \
    cp -r .next/static .next/standalone/.next/static

# Install Python scraper
RUN pip install --break-system-packages -e ./scraper

COPY run.sh /run.sh
RUN chmod +x /run.sh

ENV NODE_ENV=production
ENV PORT=3000
ENV HOSTNAME=0.0.0.0

EXPOSE 3000

CMD ["/run.sh"]
