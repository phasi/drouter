VERSION_NUMBER=$(shell git describe --tags --abbrev=0)
BRANCH=$(shell git rev-parse --abbrev-ref HEAD)
BUILD_TIME=$(shell date +'%s')
BUILD_NUMBER=$(BUILD_TIME)
VERSION="$(VERSION_NUMBER)-$(BRANCH).$(BUILD_NUMBER)"

clean:
	rm -rf build/
	rm -rf src/__pycache__
	rm -rf bin/
	rm -rf pyinstaller/
	echo "" > haproxy/haproxy.cfg

# release-patch:
# 	CURRENT_PATCH=$(shell $(VERSION_NUMBER) |cut -d '.' -f 3)

# release-minor:

# release-major:

build: clean
	cp -R src build
	sed -i.bu 's|DROUTER_VERSION="dev"|DROUTER_VERSION=$(VERSION)|g' build/drouter.py
	rm -f build/drouter.py.bu

docker: build
	docker build -t local/drouter:latest .

lbnet:
	sh test/create_lb_network.sh

deploy-drouter:
	docker stack deploy drouter -c docker-compose.yml

deploy-haproxy:
	docker stack deploy lb -c haproxy/docker-compose.yml


deploy-all: deploy-drouter deploy-haproxy
undeploy:
	docker stack rm lb drouter

bin:
	pyinstaller --onefile --nowindowed --distpath bin/ --workpath ./pyinstaller --specpath ./ -n drouter drouter.spec
