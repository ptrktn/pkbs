MODULE      = pkebs
NS          = $(MODULE)
NATS_SERVER = $(HOME)/.local/bin/nats-server
NATS_CLIENT = $(HOME)/.local/bin/nats
REGISTRY    = localhost:5000

.PHONY: install
install: $(NATS_SERVER) $(NATS_CLIENT)

$(NATS_SERVER):
	install -m 755 -d $(dir $@)
	test -f nats-server.zip || curl -sL https://github.com/nats-io/nats-server/releases/download/v2.6.5/nats-server-v2.6.5-linux-amd64.zip -o nats-server.zip
	unzip -j nats-server.zip "*/nats-server"
	install nats-server $@
	unlink nats-server

$(NATS_CLIENT): nats
	install -m 755 -d $(dir $@)
	install nats $@

nats:
	test -f nats-client.zip || curl -sL https://github.com/nats-io/natscli/releases/download/v0.0.28/nats-0.0.28-linux-amd64.zip -o nats-client.zip
	unzip -j nats-client.zip "*/nats"

.PHONY: start-nats
start-nats: $(NATS_SERVER)
	nc -zv localhost 4222 || screen -S nats -d -m $(NATS_SERVER) -js

.PHONY: stop-nats
stop-nats: $(NATS_SERVER)
	( [ ! -z "`pgrep -u $$LOGNAME nats-server`" ] && kill `pgrep -u $$LOGNAME nats-server` ) || /bin/true

.PHONY: xdeps
xdeps:
	sudo apt-get install -y netcat screen

.PHONY: deploy
deploy:
	kubectl create ns $(NS) 2> /dev/null || true
	kubectl get ns $(NS)
	kustomize build . | kubectl -n $(NS) apply -f -

.PHONY: clean-deploy
clean-deploy:
	kubectl delete --ignore-not-found=true ns $(NS)

.PHONY: bootstrap-k3s
bootstrap-k3s:
	curl -sfL https://get.k3s.io | tee k3s_install.sh | sh -s - server --write-kubeconfig-mode "0644"
	install -d $(HOME)/.kube
	install -m 0600 /etc/rancher/k3s/k3s.yaml $(HOME)/.kube/config
	$(MAKE) deploy

.PHONY: clean-k3s
clean-k3s:
	k3s-uninstall.sh

.PHONY: install-nats
install-nats:
	helm repo add nats https://nats-io.github.io/k8s/helm/charts/
	helm repo update
	helm install my-nats --set auth.enabled=true,auth.user=my-user,auth.password=T0pS3cr3t nats/nats

.PHONY: start-registry
start-registry:
	test -d /var/tmp/registry || install -d /var/tmp/registry
	(docker ps | grep -qw registry) || docker run -d -p 5000:5000 --restart=always --name registry -v /var/tmp/registry:/var/lib/registry registry:2

.PHONY: stop-registry
stop-registry:
	(docker ps | grep -qw registry) && docker container stop registry

.PHONY: build
build: nats
	docker build . -t $(MODULE)-worker
	docker tag $(MODULE)-worker $(REGISTRY)/$(MODULE)-worker
	docker push $(REGISTRY)/$(MODULE)-worker

.PHONY: clean
clean:
	rm -f nats-server.zip nats-client.zip k3s_install.sh nats

test:
	bash test.sh

