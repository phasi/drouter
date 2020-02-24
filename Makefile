
clean:
	rm -rf src/__pycache__
	echo "" > haproxy/haproxy.cfg

docker:
	docker build -t local/drouter:latest .

lbnet:
	sh test/create_lb_network.sh

deploy-drouter:
	docker stack deploy drouter -c docker-compose.yml

deploy-haproxy:
	docker stack deploy lb -c haproxy/docker-compose.yml


deploy-all: docker deploy-drouter deploy-haproxy
undeploy:
	docker stack rm lb drouter