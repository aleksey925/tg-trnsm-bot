img:
	docker build -t ghcr.io/aleksey925/tg-trnsm-bot:latest .

lint:
	@prek run --all-files
