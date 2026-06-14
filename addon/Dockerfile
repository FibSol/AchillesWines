FROM node:22-alpine

# Build tools required for better-sqlite3 native module
RUN apk add --no-cache python3 py3-pip make g++ git tzdata

WORKDIR /app

# Clone the Achilles Wines repository at build time.
# The ADD below fetches the latest commit metadata for the branch; its content
# changes on every push, which invalidates Docker's layer cache and forces a
# fresh `git clone` on every rebuild. (The old static CACHEBUST=1.0.2 never
# changed, so Docker reused a stale cached clone and the add-on was frozen at
# an old commit regardless of manifest version bumps.)
ARG REPO=https://github.com/FibSol/AchillesWines.git
ARG BRANCH=main
ADD https://api.github.com/repos/FibSol/AchillesWines/commits/${BRANCH} /tmp/main-commit.json
RUN git clone --depth=1 --branch ${BRANCH} ${REPO} .

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
