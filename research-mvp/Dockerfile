FROM python:3.14-slim
WORKDIR /app
COPY requirements.lock ./requirements.lock
RUN pip install --no-cache-dir -r requirements.lock
COPY app ./app
COPY scripts ./scripts
COPY supabase ./supabase
RUN useradd --uid 10001 --create-home fullmark && mkdir /app/data && chown fullmark /app/data
USER fullmark
EXPOSE 8000
CMD ["python", "-m", "app.launch"]
