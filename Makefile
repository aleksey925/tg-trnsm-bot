img:
	docker build -t transmission-telegram-bot:latest .

lint:
	pre-commit run --all-files
