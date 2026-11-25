
test:
	pytest tests/ -v

lint:
	ruff check .

build:
	docker build -t aeropulse-poller .

up:
	docker compose up --build

down:
	docker compose down
