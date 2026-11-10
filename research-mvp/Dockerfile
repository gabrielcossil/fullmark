FROM node:24-alpine AS editor
WORKDIR /editor
COPY editor/package.json editor/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY editor/editor.js ./source.js
RUN ./node_modules/.bin/esbuild source.js --bundle --minify --format=iife --legal-comments=eof --outfile=editor.js

FROM python:3.14-slim
WORKDIR /app
COPY requirements.lock ./requirements.lock
RUN pip install --no-cache-dir -r requirements.lock
COPY app ./app
COPY --from=editor /editor/editor.js ./app/static/editor.js
COPY scripts ./scripts
COPY supabase ./supabase
RUN useradd --uid 10001 --create-home fullmark && mkdir /app/data && chown fullmark /app/data
USER fullmark
EXPOSE 8000
CMD ["python", "-m", "app.launch"]
